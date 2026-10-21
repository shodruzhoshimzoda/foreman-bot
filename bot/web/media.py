"""Медиа задач (фото, голосовые) для дашборда.

* Telegram отдаёт файлы только через Bot API (getFile → скачивание). Сервер скачивает файл один раз
  и держит копию в дисковом кэше с ограничением размера — повторные просмотры не трогают Telegram.
* <img> и <audio> не умеют слать заголовок Authorization, поэтому дашборд получает для каждого медиа
  ссылку с подписью (HMAC) и сроком жизни 6–12 часов. Подпись выдаётся только вместе с данными шефа.
* Голосовые в Telegram — OGG/Opus; iOS-WebView их не проигрывает, поэтому по запросу (?fmt=m4a)
  сервер перекодирует их в AAC через ffmpeg (если установлен) и тоже кэширует.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import shutil
import time
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

log = logging.getLogger(__name__)

URL_BUCKET = 6 * 3600          # подпись живёт от 6 до 12 часов; внутри окна ссылка стабильна → кэш браузера работает
EXT = {"photo": ".jpg", "voice": ".ogg"}
FFMPEG_TIMEOUT = 40
PRUNE_EVERY = 25               # проверять размер кэша раз в N скачиваний


class MediaUnavailable(Exception):
    """Файла нет / слишком большой (>20 МБ для Bot API) / недоступен."""


class MediaError(Exception):
    """Временный сбой (сеть, ffmpeg)."""


class MediaStore:
    def __init__(self, bot: Bot, cache_dir: str | Path, max_mb: int, bot_token: str):
        self.bot = bot
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_mb * 1024 * 1024
        self._secret = hashlib.sha256(b"media:" + bot_token.encode()).digest()
        self._locks: dict[str, asyncio.Lock] = {}
        self._writes = 0
        self.ffmpeg = shutil.which("ffmpeg")

    # ---------------------------------------------------------------- подписанные ссылки
    def _sig(self, task_id: int, exp: int) -> str:
        return hmac.new(self._secret, f"{task_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]

    def url(self, task_id: int) -> str:
        exp = (int(time.time()) // URL_BUCKET + 2) * URL_BUCKET
        return f"/api/media/{task_id}?exp={exp}&sig={self._sig(task_id, exp)}"

    def verify(self, task_id: int, exp: str, sig: str) -> bool:
        try:
            exp_i = int(exp)
        except (TypeError, ValueError):
            return False
        return exp_i > time.time() and hmac.compare_digest(self._sig(task_id, exp_i), sig or "")

    # ---------------------------------------------------------------- файлы
    def _path(self, file_id: str, kind: str, suffix: str | None = None) -> Path:
        key = hashlib.sha1(file_id.encode()).hexdigest()
        return self.dir / (key + (suffix or EXT.get(kind, ".bin")))

    async def fetch(self, file_id: str, kind: str) -> Path:
        path = self._path(file_id, kind)
        async with self._lock(path):             # одновременные запросы одного файла качают его один раз
            if path.exists():
                os.utime(path)                   # «свежесть» для вытеснения старых файлов
                return path
            try:
                tg_file = await self.bot.get_file(file_id)
                tmp = path.with_name(path.name + ".part")
                await self.bot.download_file(tg_file.file_path, destination=tmp)
                os.replace(tmp, path)
            except (TelegramBadRequest, TelegramForbiddenError) as e:
                raise MediaUnavailable(str(e)) from e
            except (TelegramAPIError, OSError) as e:
                raise MediaError(str(e)) from e
        self._writes += 1
        if self._writes % PRUNE_EVERY == 0:
            await asyncio.to_thread(self.prune)
        return path

    async def fetch_m4a(self, file_id: str) -> Path:
        if not self.ffmpeg:
            raise MediaUnavailable("ffmpeg не установлен")
        out = self._path(file_id, "voice", ".m4a")
        async with self._lock(out):
            if out.exists():
                os.utime(out)
                return out
        src = await self.fetch(file_id, "voice")
        async with self._lock(out):
            if out.exists():
                return out
            tmp = out.with_name(out.stem + ".part.m4a")
            proc = await asyncio.create_subprocess_exec(
                self.ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(src),
                "-vn", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(tmp),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, err = await asyncio.wait_for(proc.communicate(), FFMPEG_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                raise MediaError("ffmpeg timeout")
            if proc.returncode != 0:
                tmp.unlink(missing_ok=True)
                raise MediaError(f"ffmpeg: {err.decode(errors='replace')[:200]}")
            os.replace(tmp, out)
        return out

    def _lock(self, path: Path) -> asyncio.Lock:
        lock = self._locks.get(path.name)
        if lock is None:
            if len(self._locks) > 500:
                self._locks = {k: v for k, v in self._locks.items() if v.locked()}
            lock = self._locks[path.name] = asyncio.Lock()
        return lock

    # ---------------------------------------------------------------- размер кэша
    def prune(self) -> int:
        """Удаляет самые давние файлы, пока кэш больше лимита (до 80% лимита). Возвращает число удалённых."""
        files = []
        for f in self.dir.iterdir():
            try:
                st = f.stat()
            except OSError:
                continue
            if f.name.endswith(".part") or ".part." in f.name:
                if time.time() - st.st_mtime > 3600:   # брошенные недокачанные файлы
                    f.unlink(missing_ok=True)
                continue
            files.append((st.st_mtime, st.st_size, f))
        total = sum(s for _, s, _ in files)
        if total <= self.max_bytes:
            return 0
        removed = 0
        for _, size, f in sorted(files):
            if total <= self.max_bytes * 0.8:
                break
            f.unlink(missing_ok=True)
            total -= size
            removed += 1
        log.info("Кэш медиа очищен: удалено %s файлов", removed)
        return removed

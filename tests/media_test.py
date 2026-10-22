"""
Фото и голосовые в дашборде: подписанные ссылки, дисковый кэш, Range, превью, ogg→m4a, лента задач.

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres python -m tests.media_test
"""
import asyncio
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import asyncpg
from aiogram.exceptions import TelegramBadRequest
from aiohttp.test_utils import TestClient, TestServer

from bot.config import Config
from bot.db import Database
from bot.web.media import MediaStore
from bot.web.server import build_web_app
from tests.smoke_test import TOKEN, TZ, sign_init_data

CHIEF, OTHER, F1, F2, F3 = 7_113_457_025, 2, 10, 11, 20
JPEG = b"\xff\xd8\xff\xe0" + b"JPEGDATA" * 500 + b"\xff\xd9"


class FakeBot:
    """Подменяет Telegram: getFile + скачивание. Считает обращения, чтобы проверить кэш."""

    def __init__(self, ogg: bytes):
        self.ogg = ogg
        self.get_file_calls: list[str] = []
        self.broken: set[str] = set()

    async def get_file(self, file_id):
        self.get_file_calls.append(file_id)
        if file_id in self.broken:
            raise TelegramBadRequest(method=None, message="Bad Request: file is too big")
        return SimpleNamespace(file_path=f"x/{file_id}")

    async def download_file(self, file_path, destination):
        fid = file_path.split("/", 1)[1]
        data = self.ogg if fid.startswith("VOICE") else JPEG + fid.encode()
        Path(destination).write_bytes(data)


def make_ogg() -> bytes:
    out = Path(tempfile.mkdtemp()) / "v.ogg"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "libopus", str(out)], check=True,
    )
    return out.read_bytes()


async def main() -> None:
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("Задайте TEST_DATABASE_URL")
    schema = "m_" + uuid.uuid4().hex[:8]
    db = Database(dsn, schema=schema)
    await db.connect()
    cache = tempfile.mkdtemp()
    try:
        await run(db, dsn, cache)
    finally:
        await db.close()
        c = await asyncpg.connect(dsn)
        await c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await c.close()


async def run(db: Database, dsn: str, cache: str) -> None:
    await db.upsert_chief(CHIEF, "Шеф")
    await db.upsert_chief(OTHER, "Другой")
    for fid, name, chief in ((F1, "Иванов", CHIEF), (F2, "Петров", CHIEF), (F3, "Чужой", OTHER)):
        await db.register_foreman(fid, name, None, chief)
        await db.set_user_status(fid, "active")

    t_text = (await db.create_tasks(CHIEF, [F1], "text", None, "просто текст", "normal"))[0]["id"]
    t_photo = (await db.create_tasks(CHIEF, [F1], "photo", "PHOTO_FULL", "армирование", "high",
                                     thumb_id="PHOTO_THUMB"))[0]["id"]
    t_old_photo = (await db.create_tasks(CHIEF, [F2], "photo", "OLD_FULL", "", "normal"))[0]["id"]  # без превью
    t_voice = (await db.create_tasks(CHIEF, [F2], "voice", "VOICE_1", "", "urgent", duration=7))[0]["id"]
    t_other = (await db.create_tasks(OTHER, [F3], "photo", "OTHER_FULL", "чужое", "normal"))[0]["id"]
    await db.transition(t_voice, "done")
    await db.transition(t_text, "failed")

    bot = FakeBot(make_ogg())
    cfg = Config(TOKEN, (CHIEF, OTHER), dsn, TZ, 8, media_cache_dir=cache, media_cache_mb=500)
    app = build_web_app(db, cfg, bot=bot)
    store: MediaStore = next(v for v in app.values() if isinstance(v, MediaStore))
    client = TestClient(TestServer(app))
    await client.start_server()
    h = lambda uid: {"Authorization": "tma " + sign_init_data(uid)}

    try:
        # ---- данные дашборда содержат подписанные ссылки только для фото/голосовых
        d = await (await client.get("/api/dashboard?days=7", headers=h(CHIEF))).json()
        assert d["media_enabled"] is True
        by_id = {t["id"]: t for t in d["recent"]}
        assert by_id[t_text]["media"] is None
        assert by_id[t_photo]["media"]["url"].startswith(f"/api/media/{t_photo}?exp=")
        assert by_id[t_voice]["media"]["duration"] == 7 and by_id[t_photo]["media"]["duration"] is None
        url_photo, url_old, url_voice = by_id[t_photo]["media"]["url"], by_id[t_old_photo]["media"]["url"], by_id[t_voice]["media"]["url"]

        # ---- фото: полный размер, кэш, Range
        r = await client.get(url_photo)
        assert r.status == 200 and r.content_type == "image/jpeg", (r.status, r.content_type)
        assert (await r.read()).startswith(b"\xff\xd8\xff\xe0") and r.headers["Cache-Control"].startswith("private")
        assert bot.get_file_calls == ["PHOTO_FULL"]
        await client.get(url_photo)
        assert bot.get_file_calls == ["PHOTO_FULL"], "второй запрос должен идти из кэша на диске"
        r = await client.get(url_photo, headers={"Range": "bytes=0-9"})
        assert r.status == 206 and len(await r.read()) == 10

        # ---- превью: берётся thumb_id; у старой задачи без превью — полный файл
        r = await client.get(url_photo + "&v=thumb")
        assert r.status == 200 and (await r.read()).endswith(b"PHOTO_THUMB")
        r = await client.get(url_old + "&v=thumb")
        assert r.status == 200 and (await r.read()).endswith(b"OLD_FULL")
        assert "OLD_FULL" in bot.get_file_calls

        # ---- голосовое: ogg как есть и m4a для iOS
        r = await client.get(url_voice)
        assert r.status == 200 and r.content_type == "audio/ogg" and (await r.read())[:4] == b"OggS"
        r = await client.get(url_voice + "&fmt=m4a")
        body = await r.read()
        assert r.status == 200 and r.content_type == "audio/mp4" and body[4:8] == b"ftyp", (r.status, body[:12])
        n = len(bot.get_file_calls)
        await client.get(url_voice + "&fmt=m4a")
        assert len(bot.get_file_calls) == n                      # m4a тоже из кэша
        r = await client.get(url_voice + "&fmt=m4a", headers={"Range": "bytes=0-"})
        assert r.status == 206                                    # iOS требует Range для <audio>
        # фото нельзя запросить как m4a — параметр игнорируется
        assert (await client.get(url_photo + "&fmt=m4a")).content_type == "image/jpeg"

        # ---- защита ссылок
        exp = url_photo.split("exp=")[1].split("&")[0]
        sig = url_photo.split("sig=")[1].split("&")[0]
        assert (await client.get(f"/api/media/{t_photo}")).status == 403
        assert (await client.get(f"/api/media/{t_photo}?exp={exp}&sig={'0' * 32}")).status == 403
        assert (await client.get(f"/api/media/{t_voice}?exp={exp}&sig={sig}")).status == 403   # подпись чужой задачи
        old_exp = int(time.time()) - 10
        assert (await client.get(f"/api/media/{t_photo}?exp={old_exp}&sig={store._sig(t_photo, old_exp)}")).status == 403
        assert (await client.get(f"/api/media/{t_text}?exp={exp}&sig={store._sig(t_text, int(exp))}")).status == 404  # нет медиа
        assert (await client.get("/api/media/abc")).status == 404

        # ---- шеф не получает ссылку на чужую задачу
        d2 = await (await client.get("/api/dashboard", headers=h(OTHER))).json()
        assert [t["id"] for t in d2["recent"]] == [t_other]
        assert all(t["id"] != t_other for t in d["recent"])

        # ---- ошибки Telegram не роняют сервер
        bot.broken.add("OLD_FULL")
        os.remove(store._path("OLD_FULL", "photo"))
        assert (await client.get(url_old)).status == 404

        # ---- лента задач: страницы, фильтры, изоляция
        feed = lambda qs, uid=CHIEF: client.get("/api/tasks" + qs, headers=h(uid))
        assert (await client.get("/api/tasks")).status == 401
        p1 = await (await feed("?limit=2")).json()
        assert [t["id"] for t in p1["tasks"]] == [t_voice, t_old_photo] and p1["next"] == t_old_photo
        p2 = await (await feed(f"?limit=2&before={p1['next']}")).json()
        assert [t["id"] for t in p2["tasks"]] == [t_photo, t_text] and p2["next"] is None
        only_done = await (await feed("?status=done")).json()
        assert [t["id"] for t in only_done["tasks"]] == [t_voice] and only_done["tasks"][0]["media"]
        assert [t["id"] for t in (await (await feed(f"?foreman={F1}")).json())["tasks"]] == [t_photo, t_text]
        assert (await (await feed(f"?foreman={F3}")).json())["tasks"] == []          # чужой прораб — пусто
        assert [t["id"] for t in (await (await feed("", OTHER)).json())["tasks"]] == [t_other]
        assert (await feed("?status=wat")).status == 400 and (await feed("?limit=x")).status == 400
        assert (await client.get("/api/tasks", headers=h(F1))).status == 403          # прораб — не шеф

        # ---- альбом: несколько фото (и видео) в одной задаче
        album = [
            {"kind": "photo", "file_id": "AL_A", "thumb_id": "AL_A_T", "duration": None},
            {"kind": "photo", "file_id": "AL_B", "thumb_id": "AL_B_T", "duration": None},
            {"kind": "video", "file_id": "AL_V", "thumb_id": None, "duration": 5},
            {"kind": "photo", "file_id": "AL_D", "thumb_id": "AL_D_T", "duration": None},
        ]
        t_album = (await db.create_tasks(CHIEF, [F1], "photo", "AL_A", "четыре вложения", "high", thumb_id="AL_A_T", media=album))[0]["id"]
        assert (await db.get_task(t_album))["media"] == album                      # JSONB читается как список, а не строка
        t_vid_album = (await db.create_tasks(CHIEF, [F1], "video", "V1", "", "normal", duration=3,
                                             media=[{"kind": "video", "file_id": "V1", "thumb_id": None, "duration": 3},
                                                    {"kind": "video", "file_id": "V2", "thumb_id": None, "duration": 4}]))[0]["id"]
        feed_all = await (await client.get("/api/tasks?limit=50", headers=h(CHIEF))).json()
        by_id = {t["id"]: t for t in feed_all["tasks"]}
        m = by_id[t_album]["media"]
        assert [i["kind"] for i in m["items"]] == ["photo", "photo", "video", "photo"] and m["url"].startswith(f"/api/media/{t_album}?")
        assert by_id[t_vid_album]["media"] is None                                  # в альбоме только видео — показывать нечего
        det = (await (await client.get(f"/api/tasks/{t_album}", headers=h(CHIEF))).json())["task"]
        assert det["album"] == 4 and [i["kind"] for i in det["media"]["items"]] == ["photo", "photo", "video", "photo"]
        assert det["media"]["url"].startswith(f"/api/media/{t_album}?exp=")           # панель получает подписанную ссылку на все фото
        assert by_id[t_photo]["media"]["items"] is None                             # обычное фото — без списка
        u = m["url"]
        calls = lambda: len(bot.get_file_calls)

        r = await client.get(u + "&v=thumb")                                        # i по умолчанию = 0
        assert r.status == 200 and (await r.read()).endswith(b"AL_A_T")
        r = await client.get(u + "&v=thumb&i=1")
        assert (await r.read()).endswith(b"AL_B_T")
        r = await client.get(u + "&i=3")                                            # полный размер четвёртого
        assert r.status == 200 and (await r.read()).endswith(b"AL_D")
        assert (await client.get(u + "&i=2")).status == 404                         # это видео — как картинку не отдаём
        assert (await client.get(u + "&i=4")).status == 404 and (await client.get(u + "&i=-1")).status == 404
        assert (await client.get(u + "&i=x")).status == 404
        n = calls()
        await client.get(u + "&v=thumb&i=1")
        assert calls() == n                                                         # каждое фото кэшируется отдельно
        # у обычной задачи есть только вложение №0
        assert (await client.get(url_photo + "&i=1")).status == 404
        assert (await client.get(url_photo + "&i=0&v=thumb")).status == 200
        # ссылка альбома не открывает чужие задачи
        exp2, sig2 = u.split("exp=")[1].split("&")[0], u.split("sig=")[1].split("&")[0]
        assert (await client.get(f"/api/media/{t_photo}?exp={exp2}&sig={sig2}")).status == 403

        # ---- кэш не растёт бесконечно
        small = MediaStore(bot, cache, 0, TOKEN)
        small.max_bytes = 1
        removed = small.prune()
        assert removed >= 3 and not any(p.suffix in (".jpg", ".ogg", ".m4a") for p in Path(cache).iterdir())
    finally:
        await client.close()
    print("OK: медиа и лента задач работают")


if __name__ == "__main__":
    asyncio.run(main())

from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...]
    database_url: str
    tz: str
    digest_hour: int
    webapp_url: str = ""      # публичный HTTPS-адрес дашборда; пусто — веб-часть выключена
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    media_cache_dir: str = "data/media"
    media_cache_mb: int = 500


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните его.")

    raw_ids = os.getenv("ADMIN_IDS", "").replace(" ", "")
    try:
        admin_ids = tuple(int(x) for x in raw_ids.split(",") if x)
    except ValueError:
        raise SystemExit("ADMIN_IDS должен содержать числа через запятую.")
    if not admin_ids:
        raise SystemExit("ADMIN_IDS пуст: укажите Telegram ID хотя бы одного шефа.")

    dsn = os.getenv("DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("DATABASE_URL не задан, например: postgresql://foreman:foreman@localhost:5432/foreman")

    tz = os.getenv("TZ", "Asia/Dushanbe").strip()
    try:
        ZoneInfo(tz)
    except Exception:
        raise SystemExit(f"Неизвестный часовой пояс: {tz}")

    webapp_url = os.getenv("WEBAPP_URL", "").strip().rstrip("/")
    if webapp_url and not webapp_url.startswith("https://"):
        raise SystemExit("WEBAPP_URL должен начинаться с https:// (Telegram не открывает Mini App по http).")

    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        database_url=dsn,
        tz=tz,
        digest_hour=int(os.getenv("DIGEST_HOUR", "8")),
        webapp_url=webapp_url,
        web_host=os.getenv("WEB_HOST", "127.0.0.1"),
        web_port=int(os.getenv("WEB_PORT", "8080")),
        media_cache_dir=os.getenv("MEDIA_CACHE_DIR", "data/media"),
        media_cache_mb=int(os.getenv("MEDIA_CACHE_MB", "500")),
    )

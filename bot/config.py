from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...]
    db_path: str
    tz: str
    digest_hour: int


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

    tz = os.getenv("TZ", "Asia/Dushanbe").strip()
    try:
        ZoneInfo(tz)
    except Exception:
        raise SystemExit(f"Неизвестный часовой пояс: {tz}")

    return Config(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=os.getenv("DB_PATH", "data/bot.db"),
        tz=tz,
        digest_hour=int(os.getenv("DIGEST_HOUR", "8")),
    )

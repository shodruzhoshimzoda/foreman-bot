from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from bot.config import Config
from bot.db import Database
from bot.notify import safe_send
from bot.texts import esc

log = logging.getLogger(__name__)

TICK_SECONDS = 300
DIGEST_WINDOW_HOURS = 3  # если бот был выключен в нужный час, сводка придёт в течение 3 часов


async def _digest(bot: Bot, db: Database, config: Config) -> None:
    """Утренняя сводка шефу: сколько задач сейчас в работе у каждого прораба."""
    now = datetime.now(ZoneInfo(config.tz))
    if not (config.digest_hour <= now.hour < config.digest_hour + DIGEST_WINDOW_HOURS):
        return
    today = now.strftime("%Y-%m-%d")

    by_chief = defaultdict(list)
    for r in await db.workload_all():  # один запрос на всех шефов
        by_chief[r["chief_id"]].append(r)

    for chief in await db.list_chiefs():
        key = f"digest:{chief['tg_id']}"
        if await db.meta_get(key) == today:
            continue
        await db.meta_set(key, today)

        load = by_chief.get(chief["tg_id"], [])
        active_total = sum(r["active"] for r in load)
        if not active_total:
            continue

        lines = [f"☀️ <b>Сводка на {now.strftime('%d.%m.%Y')}</b>", "", f"Задач в работе: {active_total}", ""]
        for r in load:
            lines.append(f"• {esc(r['full_name'])} — {r['active']}")
        lines.append("\nОтметить результат: «📋 Активные задачи».")
        await safe_send(bot, chief["tg_id"], "\n".join(lines))


async def run_scheduler(bot: Bot, db: Database, config: Config) -> None:
    log.info("Планировщик запущен")
    while True:
        try:
            await _digest(bot, db, config)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в планировщике")
        await asyncio.sleep(TICK_SECONDS)

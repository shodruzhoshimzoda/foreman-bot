from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from bot.config import Config, load_config
from bot.db import Database
from bot.handlers import chief, common, fallback, foreman
from bot.notify import set_dashboard_menu
from bot.scheduler import run_scheduler
from bot.web.server import build_web_app, start_web

WEBAPP_DIST = Path(__file__).resolve().parent.parent / "webapp" / "dist"


def build_dispatcher(db: Database, config: Config) -> Dispatcher:
    # events_isolation: апдейты одного пользователя идут строго по очереди — иначе фото альбома,
    # пришедшие одновременно, обрабатывались бы параллельно, каждое со своим «выберите важность»
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    dp["db"] = db
    dp["config"] = config
    # Порядок важен: сначала общие команды, потом роли, в конце — «заглушка»
    dp.include_routers(common.router, chief.router, foreman.router, fallback.router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()

    db = Database(config.database_url)
    await db.connect()
    for admin_id in config.admin_ids:
        await db.upsert_chief(admin_id)

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(db, config)
    scheduler = asyncio.create_task(run_scheduler(bot, db, config))

    web_runner = None
    if config.webapp_url:
        web_runner = await start_web(build_web_app(db, config, WEBAPP_DIST, bot), config.web_host, config.web_port)
        await asyncio.gather(*(set_dashboard_menu(bot, i, config.webapp_url) for i in config.admin_ids))
    else:
        logging.info("WEBAPP_URL не задан — дашборд выключен")

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        # слушаем только те типы апдейтов, которые реально обрабатываем
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scheduler
        if web_runner:
            await web_runner.cleanup()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())

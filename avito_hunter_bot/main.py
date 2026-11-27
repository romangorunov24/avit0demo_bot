from __future__ import annotations

import asyncio
import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from avito.client import AvitoHttpClient
from avito.messenger import AvitoMessengerService
from bot.handlers import get_main_router
from bot.middlewares import AdminAccessMiddleware
from config import get_settings
from database.db import Database
from services.cookie_helper import cookies_from_json
from services.scheduler import AvitoMonitorService


def setup_logging(log_level: str, log_file: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.LOG_FILE)
    logger = logging.getLogger("main")

    db = Database(settings.DATABASE_PATH)
    await db.connect()

    bot_cfg = await db.get_bot_settings(default_proxy=settings.DEFAULT_PROXY)
    if settings.DEFAULT_PROXY and not await db.get_setting("proxy_url"):
        await db.set_setting("proxy_url", settings.DEFAULT_PROXY)

    async def persist_updated_cookies(new_cookies: dict[str, str]) -> None:
        await db.set_setting("avito_cookies_json", json.dumps(new_cookies, ensure_ascii=False))

    client = AvitoHttpClient(
        cookies=cookies_from_json(bot_cfg.avito_cookies_json),
        proxy_url=bot_cfg.proxy_url,
        user_agent=bot_cfg.user_agent,
        impersonate=settings.IMPERSONATE_BROWSER,
        on_cookies_updated=persist_updated_cookies,
    )
    messenger = AvitoMessengerService(client=client)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Ограничение доступа по ADMIN_IDS
    admin_middleware = AdminAccessMiddleware(settings.admin_id_list)
    dp.message.middleware(admin_middleware)
    dp.callback_query.middleware(admin_middleware)

    monitor = AvitoMonitorService(
        bot=bot,
        db=db,
        client=client,
        messenger=messenger,
        admin_ids=settings.admin_id_list,
    )

    # Передаём зависимости в хендлеры aiogram
    dp["db"] = db
    dp["client"] = client
    dp["messenger"] = messenger
    dp["monitor"] = monitor

    dp.include_router(get_main_router())

    monitor.start()
    logger.info("Бот запущен и готов к работе.")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        logger.info("Завершение работы бота...")
        await monitor.stop()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import actions, searches, settings as settings_handler, start
from bot.middlewares import AccessMiddleware
from config import settings
from database.db import init_db
from services.worker import worker_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()
    logger.info("База данных SQLite инициализирована: %s", settings.DB_PATH)

    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())

    dp.include_router(start.router)
    dp.include_router(searches.router)
    dp.include_router(settings_handler.router)
    dp.include_router(actions.router)

    bg_task = asyncio.create_task(worker_loop(bot))

    try:
        logger.info("Avito Sniper Bot (Buyer Edition) запущен и готов к работе.")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        bg_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
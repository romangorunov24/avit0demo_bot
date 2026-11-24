import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import account, actions, searches, start
from bot.middlewares import AdminMiddleware
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

    # Ограничение доступа только для администраторов из ADMIN_IDS
    dp.message.middleware(AdminMiddleware())
    dp.callback_query.middleware(AdminMiddleware())

    # Регистрация роутеров
    dp.include_router(start.router)
    dp.include_router(searches.router)
    dp.include_router(account.router)
    dp.include_router(actions.router)

    # Запуск фонового парсера и автоотправщика
    bg_task = asyncio.create_task(worker_loop(bot))

    try:
        logger.info("Бот запущен и готов к работе.")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        bg_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

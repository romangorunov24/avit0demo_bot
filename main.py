import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import actions, searches, settings as settings_handler, start
from bot.middlewares import AccessMiddleware, MenuResetMiddleware
from config import settings
from database.db import init_db
from services.worker import worker_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not settings.admin_ids_list:
        raise SystemExit("ADMIN_IDS не задан: укажите в .env свой Telegram ID (иначе бот открыт для всех).")
    if "PUT_YOUR" in settings.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан: впишите токен от @BotFather в .env.")
    await init_db()
    logger.info("База данных SQLite инициализирована: %s", settings.DB_PATH)

    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.outer_middleware(MenuResetMiddleware())
    dp.message.middleware(AccessMiddleware())
    dp.callback_query.middleware(AccessMiddleware())

    async def on_error(event: ErrorEvent) -> bool:
        """Любая необработанная ошибка: пишем в лог и не оставляем у пользователя «крутящуюся» кнопку."""
        logger.error("Необработанная ошибка в обработчике: %r", event.exception, exc_info=event.exception)
        try:
            cq = event.update.callback_query
            if cq:
                await cq.answer("Что-то пошло не так, попробуйте ещё раз", show_alert=True)
        except Exception:
            pass
        return True

    dp.errors.register(on_error)

    dp.include_router(start.router)
    dp.include_router(searches.router)
    dp.include_router(settings_handler.router)
    dp.include_router(actions.router)

    bg_task = asyncio.create_task(worker_loop(bot))

    def _worker_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception():
            logger.critical("Фоновый мониторинг аварийно остановился: %r. Перезапустите бота.", task.exception())

    bg_task.add_done_callback(_worker_done)

    try:
        logger.info("Avito Sniper Pro запущен и готов к работе.")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        bg_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
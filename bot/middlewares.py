from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from config import settings
from database import db
from bot.keyboards import MENU_TEXTS


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        if not settings.admin_ids_list:
            return None

        if user.id in settings.admin_ids_list:
            return await handler(event, data)

        if await db.is_user_allowed(user.id):
            return await handler(event, data)

        return None


class MenuResetMiddleware(BaseMiddleware):
    """Нажатие кнопки меню или команды посреди ввода сбрасывает ввод, а не принимается за ответ.

    Подключается как outer-middleware: срабатывает до проверки состояний у обработчиков.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        text = getattr(event, "text", None)
        state = data.get("state")
        if state is not None and data.get("raw_state") and text and (text in MENU_TEXTS or text.startswith("/")):
            await state.clear()
            data["raw_state"] = None  # фильтры состояний берут значение из data, обновляем и его
        return await handler(event, data)

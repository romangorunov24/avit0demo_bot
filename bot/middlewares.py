from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from config import settings
from database import db


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

        # Если ADMIN_IDS пуст — свободный режим для любых покупателей и устройств
        if not settings.admin_ids_list:
            return await handler(event, data)

        if user.id in settings.admin_ids_list:
            return await handler(event, data)

        if await db.is_user_allowed(user.id):
            return await handler(event, data)

        return None
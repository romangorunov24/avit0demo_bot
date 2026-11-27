from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


class AdminAccessMiddleware(BaseMiddleware):
    """Ограничивает доступ к боту только пользователям из списка ADMIN_IDS."""

    def __init__(self, admin_ids: list[int]):
        self.admin_ids = set(admin_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        # Если ADMIN_IDS не заполнен в .env, подсказываем пользователю его ID
        if not self.admin_ids:
            msg_text = (
                f"⚠️ Список <code>ADMIN_IDS</code> в файле <code>.env</code> пуст.\n"
                f"Ваш Telegram ID: <code>{user.id}</code>\n"
                f"Добавьте <code>ADMIN_IDS={user.id}</code> в <code>.env</code> и перезапустите бота."
            )
            if isinstance(event, Message):
                await event.answer(msg_text, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer("Настройте ADMIN_IDS в .env", show_alert=True)
            return None

        if user.id not in self.admin_ids:
            logger.warning("Попытка несанкционированного доступа от user_id=%s", user.id)
            if isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён. Этот бот является приватным.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            return None

        return await handler(event, data)

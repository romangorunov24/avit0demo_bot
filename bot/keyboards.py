from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Мои поиски"), KeyboardButton(text="➕ Добавить поиск")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def account_menu_kb(is_connected: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🗑 Очистить данные сессии", callback_data="acc_disconnect")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")]]
    )


def skip_or_cancel_kb(skip_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data=skip_cb)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")],
        ]
    )


def searches_list_kb(searches: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for s in searches:
        status_icon = "🟢" if s.get("is_active", 1) else "⏸"
        rows.append([InlineKeyboardButton(text=f"{status_icon} {s['name']}", callback_data=f"search_{s['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить поиск", callback_data="add_search")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_detail_kb(search_id: int, is_active: bool = True, auto_reply: bool = False) -> InlineKeyboardMarkup:
    toggle_text = "⏸ Приостановить" if is_active else "▶️ Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=f"toggle_search_{search_id}")],
            [InlineKeyboardButton(text="🗑 Удалить поиск", callback_data=f"del_search_{search_id}")],
            [InlineKeyboardButton(text="⬅️ Назад к спискам", callback_data="back_searches")],
        ]
    )


def item_card_kb(item_url: str, item_id: int | str, seller_id: str | None = None, has_account: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔗 Открыть на Авито", url=item_url)]]
    if seller_id:
        rows.append([InlineKeyboardButton(text="🚫 Продавца в ЧС", callback_data=f"ban_{seller_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

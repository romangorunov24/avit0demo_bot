from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Мои поиски"), KeyboardButton(text="➕ Добавить поиск")],
            [KeyboardButton(text="👤 Мой Avito"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def account_menu_kb(is_connected: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="💻 Подключить с ПК (файл / JSON)", callback_data="acc_connect_pc")],
        [InlineKeyboardButton(text="📱 Подключить с телефона (без ПК)", callback_data="acc_connect_mobile")],
        [InlineKeyboardButton(text="💬 Шаблон автоотклика", callback_data="acc_set_template")],
    ]
    if is_connected:
        buttons.append([InlineKeyboardButton(text="🔄 Проверить сессию", callback_data="acc_check")])
        buttons.append([InlineKeyboardButton(text="🗑 Отвязать аккаунт", callback_data="acc_disconnect")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")]]
    )


def searches_list_kb(searches: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for s in searches:
        status_icon = "🟢" if s.get("is_active", True) else "⏸"
        name = s.get("name") or f"Поиск #{s.get('id')}"
        rows.append(
            [InlineKeyboardButton(text=f"{status_icon} {name}", callback_data=f"search_{s['id']}")]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить поиск", callback_data="add_search")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_detail_kb(search_id: int, is_active: bool = True, auto_reply: bool = True) -> InlineKeyboardMarkup:
    toggle_text = "⏸ Приостановить" if is_active else "▶️ Включить"
    reply_text = "💬 Автоотклик: ВКЛ" if auto_reply else "🔕 Автоотклик: ВЫКЛ"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"toggle_search_{search_id}"),
                InlineKeyboardButton(text=reply_text, callback_data=f"toggle_reply_{search_id}"),
            ],
            [InlineKeyboardButton(text="✏️ Изменить шаблон", callback_data=f"edit_tpl_{search_id}")],
            [InlineKeyboardButton(text="🗑 Удалить поиск", callback_data=f"del_search_{search_id}")],
            [InlineKeyboardButton(text="⬅️ Назад к спискам", callback_data="back_searches")],
        ]
    )


def item_card_kb(item_url: str, item_id: int | str, seller_id: str | None, has_account: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔗 Открыть на Авито", url=item_url)],
    ]
    if has_account:
        action_row = [InlineKeyboardButton(text="💬 Написать ещё", callback_data=f"reply_{item_id}")]
        if seller_id:
            action_row.append(InlineKeyboardButton(text="🚫 Продавца в ЧС", callback_data=f"ban_{seller_id}"))
        rows.append(action_row)
    else:
        rows.append([InlineKeyboardButton(text="⚡ Подключить Avito для автоотклика", callback_data="acc_menu_open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

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

from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Мои поиски и фильтры", callback_data="searches:list")
    kb.button(text="➕ Добавить новый поиск", callback_data="searches:add")
    kb.button(text="👤 Аккаунт Avito и Автоответ", callback_data="account:menu")
    kb.button(text="🔄 Обновить статистику", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def searches_list_kb(searches: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for s in searches:
        status = "🟢" if s["is_active"] else "⏸"
        sniper = f" | 🎯 ≤{s['sniper_price']}₽" if s["sniper_price"] > 0 else ""
        kb.button(
            text=f"{status} {s['name']}{sniper}",
            callback_data=f"search:view:{s['id']}",
        )
    kb.button(text="➕ Добавить поиск", callback_data="searches:add")
    kb.button(text="⬅️ В главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def search_detail_kb(s: dict[str, Any]) -> InlineKeyboardMarkup:
    sid = s["id"]
    kb = InlineKeyboardBuilder()
    toggle_text = "⏸ Поставить на паузу" if s["is_active"] else "▶️ Включить поиск"
    private_text = "👤 Только частники: ВКЛ" if s["only_private"] else "👤 Только частники: ВЫКЛ"

    kb.button(text=toggle_text, callback_data=f"search:toggle:{sid}")
    kb.button(text="💰 Мин / Макс цена", callback_data=f"search:price:{sid}")
    kb.button(text="🎯 Порог «Снайпер» (автоответ)", callback_data=f"search:sniper:{sid}")
    kb.button(text="🚫 Минус-слова", callback_data=f"search:stop:{sid}")
    kb.button(text="✅ Плюс-слова", callback_data=f"search:plus:{sid}")
    kb.button(text=private_text, callback_data=f"search:private:{sid}")
    kb.button(text="🗑 Удалить поиск", callback_data=f"search:delete:{sid}")
    kb.button(text="⬅️ К списку поисков", callback_data="searches:list")
    kb.adjust(1)
    return kb.as_markup()


def account_menu_kb(
    account: dict[str, Any] | None,
    auto_reply: bool,
    night_mode: bool,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    ar_text = "🤖 Автоответ: ВКЛ" if auto_reply else "🤖 Автоответ: ВЫКЛ"
    nm_text = "🌙 Ночной режим (00–07): ВКЛ" if night_mode else "🌙 Ночной режим (00–07): ВЫКЛ"

    kb.button(text="🍪 Загрузить Cookies Avito", callback_data="account:cookies")
    kb.button(text=ar_text, callback_data="account:toggle_autoreply")
    kb.button(text="✍️ Шаблон сообщения (Spintax)", callback_data="account:spintax")
    kb.button(text="⏱ Лимит сообщений в час", callback_data="account:limit")
    kb.button(text=nm_text, callback_data="account:toggle_night")
    kb.button(text="⬅️ В главное меню", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def item_notification_kb(item_url: str, item_id: str, seller_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔗 Открыть на Авито", url=item_url))
    kb.row(
        InlineKeyboardButton(text="💬 Написать ещё", callback_data=f"act:msg:{item_id}"),
        InlineKeyboardButton(text="🚫 Продавца в ЧС", callback_data=f"act:bl:{seller_id}"),
    )
    return kb.as_markup()


def cancel_kb(callback_data: str = "menu:main") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ Отмена", callback_data=callback_data)
    return kb.as_markup()

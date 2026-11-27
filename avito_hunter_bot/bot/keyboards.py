from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import SearchTask


def main_menu_kb(auto_reply_enabled: bool) -> InlineKeyboardMarkup:
    ar_label = "🟢 Автоотклик: ВКЛ" if auto_reply_enabled else "🔴 Автоотклик: ВЫКЛ"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔍 Поиски", callback_data="menu:searches"),
                InlineKeyboardButton(text="➕ Новый поиск", callback_data="search:add"),
            ],
            [
                InlineKeyboardButton(text="👤 Аккаунт Avito", callback_data="menu:account"),
                InlineKeyboardButton(text="🌐 Прокси и сеть", callback_data="menu:proxy"),
            ],
            [
                InlineKeyboardButton(text=ar_label, callback_data="autoreply:toggle_global"),
                InlineKeyboardButton(text="💬 Настройки отклика", callback_data="menu:autoreply"),
            ],
            [
                InlineKeyboardButton(text="⚡️ Проверить всё сейчас", callback_data="menu:run_now"),
                InlineKeyboardButton(text="📊 Статистика", callback_data="menu:stats"),
            ],
        ]
    )


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")]
        ]
    )


def cancel_fsm_kb(back_callback: str = "menu:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=back_callback)]
        ]
    )


def searches_list_kb(searches: list[SearchTask]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for s in searches:
        status_icon = "🟢" if s.is_active else "⏸"
        ar_icon = "💬" if s.auto_reply else "🔕"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status_icon} {ar_icon} {s.name}",
                    callback_data=f"search:view:{s.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить поиск", callback_data="search:add")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_detail_kb(task: SearchTask) -> InlineKeyboardMarkup:
    toggle_text = "⏸ Приостановить" if task.is_active else "▶️ Включить поиск"
    ar_text = "🔕 Выкл. автоотклик" if task.auto_reply else "💬 Вкл. автоотклик"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"search:toggle:{task.id}"),
                InlineKeyboardButton(text=ar_text, callback_data=f"search:toggle_ar:{task.id}"),
            ],
            [
                InlineKeyboardButton(text="⚡️ Проверить сейчас", callback_data=f"search:scan:{task.id}"),
                InlineKeyboardButton(text="✏️ Шаблон отклика", callback_data=f"search:edit_tpl:{task.id}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Удалить поиск", callback_data=f"search:delete:{task.id}"),
            ],
            [
                InlineKeyboardButton(text="⬅️ К списку поисков", callback_data="menu:searches"),
                InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main"),
            ],
        ]
    )


def account_menu_kb(has_cookies: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔑 Загрузить / обновить Cookies", callback_data="account:set_cookies")],
        [InlineKeyboardButton(text="🩺 Проверить авторизацию", callback_data="account:check")],
    ]
    if has_cookies:
        rows.append([InlineKeyboardButton(text="🗑 Удалить Cookies", callback_data="account:clear_cookies")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def proxy_menu_kb(has_proxy: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🌐 Установить / сменить прокси", callback_data="proxy:set")],
        [InlineKeyboardButton(text="🩺 Диагностика сети и IP", callback_data="proxy:diagnose")],
    ]
    if has_proxy:
        rows.append([InlineKeyboardButton(text="🗑 Отключить прокси", callback_data="proxy:clear")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def autoreply_menu_kb(auto_reply_enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Выключить автоотклик" if auto_reply_enabled else "🟢 Включить автоотклик"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data="autoreply:toggle_global")],
            [InlineKeyboardButton(text="✏️ Изменить общий шаблон", callback_data="autoreply:edit_tpl")],
            [InlineKeyboardButton(text="🛡 Лимиты и задержки", callback_data="autoreply:edit_limits")],
            [InlineKeyboardButton(text="⏱ Интервал сканирования", callback_data="autoreply:edit_interval")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
        ]
    )

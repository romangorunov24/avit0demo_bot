from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Мои поиски"), KeyboardButton(text="➕ Добавить поиск")],
            [KeyboardButton(text="⭐ Избранное"), KeyboardButton(text="⚙️ Настройки и Автоматизация")],
        ],
        resize_keyboard=True,
    )


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
        rows.append([InlineKeyboardButton(text=f"{status_icon} {s['name']}", callback_data=f"sview_{s['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить поиск", callback_data="add_search")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_detail_kb(search_id: int, is_active: bool = True, seller_filter: str = "all") -> InlineKeyboardMarkup:
    toggle_text = "⏸ На паузу" if is_active else "▶️ Включить"
    sf_labels = {"all": "👤 Продавцы: Все", "private": "👤 Только частники", "company": "🏢 Только магазины"}
    sf_text = sf_labels.get(seller_filter or "all", "👤 Продавцы: Все")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"stoggle_{search_id}"),
                InlineKeyboardButton(text="🔄 Проверить сейчас", callback_data=f"srun_{search_id}"),
            ],
            [
                InlineKeyboardButton(text="💰 Мин/Макс цена", callback_data=f"sedit_price_{search_id}"),
                InlineKeyboardButton(text="🚨 Снайпер-цена", callback_data=f"sedit_sniper_{search_id}"),
            ],
            [
                InlineKeyboardButton(text="✅ Плюс-слова", callback_data=f"sedit_plus_{search_id}"),
                InlineKeyboardButton(text="🚫 Стоп-слова", callback_data=f"sedit_stop_{search_id}"),
            ],
            [
                InlineKeyboardButton(text=sf_text, callback_data=f"sedit_seller_{search_id}"),
                InlineKeyboardButton(text="💬 Свой шаблон", callback_data=f"sedit_tpl_{search_id}"),
            ],
            [
                InlineKeyboardButton(text="✏️ Название", callback_data=f"sedit_name_{search_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sdel_{search_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад к спискам", callback_data="back_searches")],
        ]
    )


def item_card_kb(item_url: str, item_id: int | str, seller_id: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🚀 Открыть в Avito (отправить)", url=item_url)],
        [
            InlineKeyboardButton(text="🔄 Ещё вариант", callback_data=f"reroll:main:{item_id}"),
            InlineKeyboardButton(text="💸 С торгом", callback_data=f"reroll:bargain:{item_id}"),
            InlineKeyboardButton(text="📦 Доставка", callback_data=f"reroll:delivery:{item_id}"),
        ],
    ]
    bottom_row = [InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav_add:{item_id}")]
    if seller_id:
        bottom_row.append(InlineKeyboardButton(text="🚫 Продавца в ЧС", callback_data=f"ban:{seller_id}"))
    rows.append(bottom_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def buyer_settings_kb(user_settings: dict[str, Any]) -> InlineKeyboardMarkup:
    is_paused = bool(user_settings.get("is_paused"))
    only_prof = bool(user_settings.get("only_profitable"))
    min_disc = user_settings.get("min_discount_pct") or 10
    sf = user_settings.get("seller_filter") or "all"
    qh = user_settings.get("quiet_hours") or "Выкл"

    pause_btn = "▶️ Возобновить работу бота" if is_paused else "⏸ Поставить бот на паузу"
    prof_btn = f"🔥 Только выгодные: ВКЛ (от {min_disc}%)" if only_prof else "🔥 Только выгодные: ВЫКЛ (шлём все)"
    sf_map = {"all": "Все", "private": "Только частники", "company": "Только магазины"}

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=pause_btn, callback_data="set_toggle_pause")],
            [InlineKeyboardButton(text=prof_btn, callback_data="set_toggle_profitable")],
            [
                InlineKeyboardButton(text=f"📉 Порог выгоды ({min_disc}%)", callback_data="set_discount_pct"),
                InlineKeyboardButton(text=f"👤 Продавцы: {sf_map.get(sf, 'Все')}", callback_data="set_seller_filter"),
            ],
            [
                InlineKeyboardButton(text=f"🌙 Тихие часы: {qh}", callback_data="set_quiet_hours"),
                InlineKeyboardButton(text="💬 Шаблоны отклика", callback_data="set_templates_menu"),
            ],
            [
                InlineKeyboardButton(text="🚫 Чёрный список", callback_data="set_blacklist_menu"),
                InlineKeyboardButton(text="🔌 Автоотклик (Опц.)", callback_data="set_avito_menu"),
            ],
        ]
    )


def templates_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Основной шаблон", callback_data="set_tpl_main")],
            [InlineKeyboardButton(text="💸 Шаблон с торгом (-10%)", callback_data="set_tpl_bargain")],
            [InlineKeyboardButton(text="📦 Шаблон про доставку", callback_data="set_tpl_delivery")],
            [InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="set_menu")],
        ]
    )


def avito_optional_kb(has_cookies: bool, auto_enabled: bool) -> InlineKeyboardMarkup:
    auto_text = "🤖 Автоотклик в фоне: ВКЛ" if auto_enabled else "🤖 Автоотклик в фоне: ВЫКЛ"
    rows = [
        [InlineKeyboardButton(text=auto_text, callback_data="acc_toggle_auto")],
        [InlineKeyboardButton(text="💻 Подключить сессию (ПК / Файл)", callback_data="acc_connect_pc")],
        [InlineKeyboardButton(text="📱 Подключить сессию (Телефон)", callback_data="acc_connect_mobile")],
    ]
    if has_cookies:
        rows.append([InlineKeyboardButton(text="🔄 Проверить сессию", callback_data="acc_check")])
        rows.append([InlineKeyboardButton(text="🗑 Отвязать аккаунт", callback_data="acc_disconnect")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="set_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
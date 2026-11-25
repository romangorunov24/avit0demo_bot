from typing import Any
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


# Тексты кнопок главного меню: нажатие любой из них сбрасывает незавершённый ввод (см. MenuResetMiddleware)
MENU_TEXTS = frozenset(
    {
        "🧭 Поиск по параметрам",
        "🔍 Мои поиски",
        "➕ Добавить поиск",
        "🤖 Автоотклик и Аккаунт",
        "⚙️ Фильтры и Настройки",
        "⭐ Избранное",
        "📖 Инструкция и Защита",
    }
)


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧭 Поиск по параметрам")],
            [KeyboardButton(text="🔍 Мои поиски"), KeyboardButton(text="➕ Добавить поиск")],
            [KeyboardButton(text="🤖 Автоотклик и Аккаунт"), KeyboardButton(text="⚙️ Фильтры и Настройки")],
            [KeyboardButton(text="⭐ Избранное"), KeyboardButton(text="📖 Инструкция и Защита")],
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
            [InlineKeyboardButton(text="⏭ Пропустить шаг", callback_data=skip_cb)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")],
        ]
    )


def confirm_delete_kb(search_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"sdelok_{search_id}")],
            [InlineKeyboardButton(text="⬅️ Нет, назад", callback_data=f"sview_{search_id}")],
        ]
    )


def city_kb() -> InlineKeyboardMarkup:
    from services.search_url import CITIES

    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for slug, (title, _) in CITIES.items():
        pair.append(InlineKeyboardButton(text=title, callback_data=f"city:{slug}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(text="✏️ Другой город (написать)", callback_data="city_other")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def memory_kb() -> InlineKeyboardMarkup:
    from services.search_url import MEMORY_CHOICES

    labels = {"1024": "1 ТБ"}
    row = [InlineKeyboardButton(text=labels.get(m, f"{m} ГБ"), callback_data=f"mem:{m}") for m in MEMORY_CHOICES]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row[:3],
            row[3:],
            [InlineKeyboardButton(text="Любая память", callback_data="mem:any")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_fsm")],
        ]
    )


def searches_list_kb(searches: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for s in searches:
        status_icon = "🟢" if s.get("is_active", 1) else "⏸"
        auto_icon = "🤖" if s.get("auto_reply", 1) else ""
        rows.append([InlineKeyboardButton(text=f"{status_icon}{auto_icon} {s['name']}", callback_data=f"sview_{s['id']}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить новый поиск", callback_data="add_search")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_detail_kb(search_id: int, is_active: bool = True, auto_reply: bool = True, seller_filter: str = "all") -> InlineKeyboardMarkup:
    toggle_text = "⏸ На паузу" if is_active else "▶️ Включить"
    auto_text = "🤖 Автоотклик: ВКЛ" if auto_reply else "🤖 Автоотклик: ВЫКЛ"
    sf_labels = {"all": "👤 Продавцы: Все", "private": "👤 Только частники", "company": "🏢 Только магазины"}
    sf_text = sf_labels.get(seller_filter or "all", "👤 Продавцы: Все")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_text, callback_data=f"stoggle_{search_id}"),
                InlineKeyboardButton(text=auto_text, callback_data=f"sauto_{search_id}"),
            ],
            [InlineKeyboardButton(text="🔄 Проверить сейчас (тест лотов)", callback_data=f"srun_{search_id}")],
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
                InlineKeyboardButton(text="🗑 Удалить поиск", callback_data=f"sdel_{search_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад к спискам", callback_data="back_searches")],
        ]
    )


def item_card_kb(item_url: str, item_id: int | str, seller_id: str | None = None, can_send_now: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔗 Открыть объявление на Avito", url=item_url)]]
    if can_send_now:
        rows.append([InlineKeyboardButton(text="📨 Отправить это сообщение в Avito", callback_data=f"send_now:{item_id}")])
    rows.append(
        [
            InlineKeyboardButton(text="🔄 Ещё текст", callback_data=f"reroll:main:{item_id}"),
            InlineKeyboardButton(text="💸 С торгом", callback_data=f"reroll:bargain:{item_id}"),
            InlineKeyboardButton(text="📦 Доставка", callback_data=f"reroll:delivery:{item_id}"),
        ]
    )
    bottom = [InlineKeyboardButton(text="⭐ В избранное", callback_data=f"fav_add:{item_id}")]
    # callback_data у Telegram не длиннее 64 байт: иначе вся клавиатура отклоняется и карточка не доходит
    if seller_id and len(f"ban:{seller_id}".encode("utf-8")) <= 64:
        bottom.append(InlineKeyboardButton(text="🚫 Продавца в ЧС", callback_data=f"ban:{seller_id}"))
    rows.append(bottom)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def auto_reply_menu_kb(has_cookies: bool, auto_enabled: bool) -> InlineKeyboardMarkup:
    master_btn = "🟢 Автоотклик: ВКЛЮЧЁН (нажмите, чтобы выкл.)" if auto_enabled else "🔴 Автоотклик: ВЫКЛЮЧЕН (нажмите, чтобы вкл.)"
    rows = [
        [InlineKeyboardButton(text=master_btn, callback_data="acc_toggle_auto")],
        [InlineKeyboardButton(text="💻 Подключить Avito с ПК (Cookie-Editor)", callback_data="acc_connect_pc")],
        [InlineKeyboardButton(text="📱 Подключить Avito с телефона", callback_data="acc_connect_mobile")],
        [InlineKeyboardButton(text="🛡 Лимиты и Антибан-защита", callback_data="set_antiban_menu")],
        [InlineKeyboardButton(text="🌐 Проверить IP и связь с Avito", callback_data="acc_net_check")],
    ]
    if has_cookies:
        rows.append(
            [
                InlineKeyboardButton(text="🔄 Проверить сессию", callback_data="acc_check"),
                InlineKeyboardButton(text="🗑 Отвязать аккаунт", callback_data="acc_disconnect"),
            ]
        )
    rows.append([InlineKeyboardButton(text="📜 Журнал отправленных откликов", callback_data="acc_history")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def antiban_menu_kb(u: dict[str, Any]) -> InlineKeyboardMarkup:
    h_lim = u.get("max_replies_hour") or 8
    d_lim = u.get("max_replies_day") or 30
    d_min = u.get("auto_delay_min") or 4
    d_max = u.get("auto_delay_max") or 10
    cd = u.get("seller_cooldown_hours") or 24
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📊 Лимиты: {h_lim}/час, {d_lim}/день", callback_data="set_ab_limits")],
            [InlineKeyboardButton(text=f"⏱ Пауза перед отправкой: {d_min}-{d_max} сек.", callback_data="set_ab_delay")],
            [InlineKeyboardButton(text=f"👤 Повтор одному продавцу: раз в {cd} ч.", callback_data="set_ab_cooldown")],
            [InlineKeyboardButton(text="⬅️ Назад в меню Автоотклика", callback_data="set_avito_menu")],
        ]
    )


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
            [InlineKeyboardButton(text="🚫 Чёрный список продавцов", callback_data="set_blacklist_menu")],
        ]
    )


def templates_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Основной шаблон отклика", callback_data="set_tpl_main")],
            [InlineKeyboardButton(text="💸 Шаблон с торгом (-10%)", callback_data="set_tpl_bargain")],
            [InlineKeyboardButton(text="📦 Шаблон про доставку", callback_data="set_tpl_delivery")],
            [InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="set_menu")],
        ]
    )


def guide_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆓 Как работать БЕЗ прокси (с ПК в РФ)", callback_data="guide_noproxy")],
            [InlineKeyboardButton(text="🔑 Как безопасно подключить Avito", callback_data="guide_cookies")],
            [InlineKeyboardButton(text="🛡 Как работает защита от банов", callback_data="guide_antiban")],
            [InlineKeyboardButton(text="💬 Спинтакс и переменные в шаблонах", callback_data="guide_spintax")],
        ]
    )
import asyncio
import html
import json
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from bot.keyboards import (
    antiban_menu_kb,
    auto_reply_menu_kb,
    buyer_settings_kb,
    cancel_kb,
    main_menu_kb,
    templates_menu_kb,
)
from bot.states import SettingsStates
from config import settings
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies
from services.proxy_helper import diagnose_connection

router = Router()


def _format_autoreply_summary(u: dict) -> str:
    cookies = normalize_cookies(u.get("avito_cookies") or "")
    auto_on = bool(u.get("auto_reply_enabled"))
    acc_line = (
        f"🟢 <b>Подключён</b> (ключи: <code>{', '.join(cookies.keys())}</code>)"
        if cookies
        else "⚪️ <b>Не подключён</b> (привяжите cookies ниже)"
    )
    mode_line = (
        "🟢 <b>ВКЛЮЧЁН</b> — бот сам пишет продавцу при выходе нового лота!"
        if (auto_on and cookies)
        else "🔴 <b>ВЫКЛЮЧЕН</b> — бот только присылает карточки в Telegram"
    )
    h_lim = u.get("max_replies_hour") or 8
    d_lim = u.get("max_replies_day") or 30
    d_min = u.get("auto_delay_min") or 4
    d_max = u.get("auto_delay_max") or 10

    return (
        "🤖 <b>Управление Автооткликом и Аккаунтом Avito</b>\n\n"
        f"• Статус аккаунта: {acc_line}\n"
        f"• Режим автоотклика: {mode_line}\n"
        f"• Антибан-лимиты: до <b>{h_lim}/час</b>, до <b>{d_lim}/сутки</b>, пауза <b>{d_min}–{d_max} сек.</b>\n\n"
        "💡 <i>Перед включением автоотклика нажмите «🌐 Проверить IP и связь с Avito», чтобы убедиться, что IP российский.</i>"
    )


def _format_settings_summary(u: dict) -> str:
    status = "⏸ На паузе" if u.get("is_paused") else "🟢 Активен"
    proxy_state = "🟢 Включён (PROXY_URL)" if settings.PROXY_URL else "🏠 Прямой IP устройства (без прокси)"
    return (
        "⚙️ <b>Фильтры и Настройки бота</b>\n\n"
        f"• Мониторинг: <b>{status}</b> (интервал ~{settings.CHECK_INTERVAL_SEC} сек.)\n"
        f"• Сетевой режим: <b>{proxy_state}</b>\n\n"
        "Настройте общие фильтры и шаблоны сообщений под свои задачи:"
    )


@router.message(F.text == "🤖 Автоотклик и Аккаунт")
async def show_autoreply_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    u = await db.get_user_settings(message.from_user.id)
    has_c = bool(normalize_cookies(u.get("avito_cookies") or ""))
    await message.answer(
        _format_autoreply_summary(u),
        parse_mode="HTML",
        reply_markup=auto_reply_menu_kb(has_c, bool(u.get("auto_reply_enabled"))),
    )


@router.callback_query(F.data == "set_avito_menu")
async def cb_autoreply_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    u = await db.get_user_settings(callback.from_user.id)
    has_c = bool(normalize_cookies(u.get("avito_cookies") or ""))
    await callback.message.edit_text(
        _format_autoreply_summary(u),
        parse_mode="HTML",
        reply_markup=auto_reply_menu_kb(has_c, bool(u.get("auto_reply_enabled"))),
    )
    await callback.answer()


@router.callback_query(F.data == "acc_toggle_auto")
async def toggle_auto_reply_master(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    has_c = bool(normalize_cookies(u.get("avito_cookies") or ""))
    if not has_c and not u.get("auto_reply_enabled"):
        await callback.answer("Сначала подключите аккаунт Avito (кнопка ниже)!", show_alert=True)
        return
    new_val = 0 if u.get("auto_reply_enabled") else 1
    await db.update_user_field(callback.from_user.id, "auto_reply_enabled", new_val)
    u["auto_reply_enabled"] = new_val
    await callback.message.edit_text(
        _format_autoreply_summary(u),
        parse_mode="HTML",
        reply_markup=auto_reply_menu_kb(has_c, bool(new_val)),
    )
    await callback.answer("Автоотклик ВКЛЮЧЁН!" if new_val else "Автоотклик ВЫКЛЮЧЕН")


@router.callback_query(F.data == "acc_net_check")
async def check_network_ip(callback: CallbackQuery) -> None:
    await callback.answer("⏳ Проверяю IP и доступ к Avito...")
    report = await diagnose_connection()
    await callback.message.answer(report, parse_mode="HTML")


@router.callback_query(F.data == "acc_connect_pc")
async def connect_pc_cookies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SettingsStates.waiting_cookies)
    await callback.message.answer(
        "💻 <b>Подключение аккаунта Avito с компьютера</b>\n\n"
        "1. Откройте <b>avito.ru</b> в браузере и войдите в свой профиль.\n"
        "2. Нажмите на расширение <b>Cookie-Editor</b> → <b>Export → Export as JSON</b>.\n"
        "3. Вставьте скопированный текст прямо сюда (или отправьте файлом <code>cookies.json</code>).\n\n"
        "💡 <i>Бот сам склеит все части сообщения и вытащит только нужные ключи.</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "acc_connect_mobile")
async def connect_mobile_cookies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SettingsStates.waiting_cookies)
    await callback.message.answer(
        "📱 <b>Подключение аккаунта Avito с телефона</b>\n\n"
        "1. Откройте <b>avito.ru</b> в браузере <b>Kiwi Browser</b> (Android) или <b>Orion</b> (iPhone) и войдите в профиль.\n"
        "2. В расширении <b>Cookie-Editor</b> нажмите <b>Export → Export as JSON</b>.\n"
        "3. Вставьте текст сюда в ответном сообщении:",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_cookies)
async def process_cookies_input(message: Message, state: FSMContext) -> None:
    raw_text = ""
    if message.document:
        if message.document.file_size and message.document.file_size > 512 * 1024:
            await message.answer("❌ Файл слишком большой (максимум 512 КБ).")
            return
        file = await message.bot.get_file(message.document.file_id)
        downloaded = await message.bot.download_file(file.file_path)
        raw_text = downloaded.read().decode("utf-8", errors="ignore")
    elif message.text:
        raw_text = message.text
    else:
        await message.answer("Отправьте текст JSON или файл <code>cookies.json</code>.", parse_mode="HTML")
        return

    cleaned = normalize_cookies(raw_text)
    data = await state.get_data()
    seq = data.get("c_seq", 0) + 1
    acc = dict(data.get("c_acc", {}))
    acc.update(cleaned)
    await state.update_data(c_seq=seq, c_acc=acc)

    if not message.document:
        await asyncio.sleep(1.2)
        latest = await state.get_data()
        if latest.get("c_seq") != seq:
            return
        acc = dict(latest.get("c_acc", {}))

    if not acc or ("sessid" not in acc and "u" not in acc):
        await state.update_data(c_acc={})
        await message.answer(
            "❌ Не удалось найти ключи <code>sessid</code> и <code>u</code>.\n"
            "Убедитесь, что вы экспортировали cookies со страницы <b>avito.ru</b> после входа в профиль, и попробуйте снова:",
            parse_mode="HTML",
            reply_markup=cancel_kb(),
        )
        return

    compact = json.dumps(acc, ensure_ascii=False)
    await db.update_user_field(message.from_user.id, "avito_cookies", compact)
    await state.clear()

    wait_msg = await message.answer("⏳ Проверяю валидность сессии на Avito...")
    messenger = AvitoMessenger()
    ok, info = await messenger.check_session(compact)
    icon = "✅" if ok else "⚠️"
    await wait_msg.edit_text(
        f"{icon} <b>{html.escape(info)}</b>\n"
        f"Сохранены ключи: <code>{', '.join(acc.keys())}</code>\n\n"
        "Теперь вы можете включить тумблер <b>«🟢 Автоотклик: ВКЛЮЧЁН»</b> в меню «🤖 Автоотклик и Аккаунт».",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "acc_check")
async def check_saved_session(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    messenger = AvitoMessenger()
    _, info = await messenger.check_session(u.get("avito_cookies"))
    await callback.answer(info[:190], show_alert=True)


@router.callback_query(F.data == "acc_disconnect")
async def disconnect_saved_session(callback: CallbackQuery) -> None:
    await db.update_user_field(callback.from_user.id, "avito_cookies", None)
    await db.update_user_field(callback.from_user.id, "auto_reply_enabled", 0)
    await callback.answer("Аккаунт отвязан, автоотклик выключен")
    await cb_autoreply_menu(callback, None)  # type: ignore[arg-type]


@router.callback_query(F.data == "acc_history")
async def show_sent_history(callback: CallbackQuery) -> None:
    rows = await db.get_recent_sent_messages(callback.from_user.id, limit=10)
    if not rows:
        await callback.answer("Журнал автооткликов пока пуст", show_alert=True)
        return
    lines = ["📜 <b>Последние 10 попыток автоотклика:</b>\n"]
    for r in rows:
        icon = "✅" if r["status"] == "sent" else "⚠️"
        lines.append(f"{icon} <b>{html.escape((r['item_title'] or 'Лот')[:35])}</b>\n<i>«{html.escape((r['message_text'] or '')[:70])}»</i>")
    await callback.message.answer("\n\n".join(lines), parse_mode="HTML")
    await callback.answer()


# --- Антибан и лимиты ---
@router.callback_query(F.data == "set_antiban_menu")
async def open_antiban_menu(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    text = (
        "🛡 <b>Настройки Антибан-защиты и лимитов</b>\n\n"
        "• <b>Лимиты в час/день:</b> защищают аккаунт от блокировки за массовую рассылку.\n"
        "• <b>Пауза перед отправкой:</b> имитирует чтение объявления человеком.\n"
        "• <b>Повтор одному продавцу:</b> не даёт спамить одному продавцу по разным товарам."
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=antiban_menu_kb(u))
    await callback.answer()


@router.callback_query(F.data == "set_ab_limits")
async def ask_ab_limits(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_ab_limits)
    await callback.message.answer(
        "📊 Введите два числа через пробел: <b>лимит в час</b> и <b>лимит в сутки</b>.\n"
        "Рекомендуемое безопасное значение: <code>8 30</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_ab_limits)
async def save_ab_limits(message: Message, state: FSMContext) -> None:
    nums = [int(x) for x in (message.text or "").split() if x.isdigit()]
    if len(nums) >= 2:
        await db.update_user_field(message.from_user.id, "max_replies_hour", max(1, min(60, nums[0])))
        await db.update_user_field(message.from_user.id, "max_replies_day", max(1, min(300, nums[1])))
    await state.clear()
    await message.answer("✅ Лимиты автооткликов обновлены!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "set_ab_delay")
async def ask_ab_delay(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_ab_delay)
    await callback.message.answer(
        "⏱ Введите минимальную и максимальную паузу в секундах через дефис (например: <code>4-10</code>):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_ab_delay)
async def save_ab_delay(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    if "-" in txt:
        a, b = txt.split("-", 1)
        d1 = int("".join(c for c in a if c.isdigit()) or 4)
        d2 = int("".join(c for c in b if c.isdigit()) or 10)
        await db.update_user_field(message.from_user.id, "auto_delay_min", max(1, min(60, d1)))
        await db.update_user_field(message.from_user.id, "auto_delay_max", max(d1, min(120, d2)))
    await state.clear()
    await message.answer("✅ Задержка перед отправкой сохранена!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "set_ab_cooldown")
async def ask_ab_cooldown(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_ab_cooldown)
    await callback.message.answer(
        "👤 Через сколько часов можно повторно писать тому же продавцу по другим объявлениям? (например: <code>24</code>):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_ab_cooldown)
async def save_ab_cooldown(message: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    val = int(digits) if digits else 24
    await db.update_user_field(message.from_user.id, "seller_cooldown_hours", max(0, min(720, val)))
    await state.clear()
    await message.answer("✅ Интервал защиты от повторов продавцу обновлён!", reply_markup=main_menu_kb())


# --- Общие фильтры и шаблоны ---
@router.message(F.text == "⚙️ Фильтры и Настройки")
async def show_settings_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    u = await db.get_user_settings(message.from_user.id)
    await message.answer(_format_settings_summary(u), parse_mode="HTML", reply_markup=buyer_settings_kb(u))


@router.callback_query(F.data == "set_menu")
async def back_to_settings_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    u = await db.get_user_settings(callback.from_user.id)
    await callback.message.edit_text(_format_settings_summary(u), parse_mode="HTML", reply_markup=buyer_settings_kb(u))
    await callback.answer()


@router.callback_query(F.data == "cancel_fsm")
async def cancel_fsm_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()


@router.callback_query(F.data == "set_toggle_pause")
async def toggle_global_pause(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    new_val = 0 if u.get("is_paused") else 1
    await db.update_user_field(callback.from_user.id, "is_paused", new_val)
    u["is_paused"] = new_val
    await callback.message.edit_text(_format_settings_summary(u), parse_mode="HTML", reply_markup=buyer_settings_kb(u))
    await callback.answer("Бот поставлен на паузу" if new_val else "Мониторинг возобновлён")


@router.callback_query(F.data == "set_toggle_profitable")
async def toggle_only_profitable(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    new_val = 0 if u.get("only_profitable") else 1
    await db.update_user_field(callback.from_user.id, "only_profitable", new_val)
    u["only_profitable"] = new_val
    await callback.message.edit_text(_format_settings_summary(u), parse_mode="HTML", reply_markup=buyer_settings_kb(u))
    await callback.answer("Фильтр выгодных лотов обновлён")


@router.callback_query(F.data == "set_seller_filter")
async def cycle_seller_filter(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    order = ["all", "private", "company"]
    cur = u.get("seller_filter") or "all"
    nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "all"
    await db.update_user_field(callback.from_user.id, "seller_filter", nxt)
    u["seller_filter"] = nxt
    await callback.message.edit_text(_format_settings_summary(u), parse_mode="HTML", reply_markup=buyer_settings_kb(u))
    await callback.answer("Фильтр продавцов обновлён")


@router.callback_query(F.data == "set_discount_pct")
async def ask_discount_pct(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_discount_pct)
    await callback.message.answer(
        "📉 Введите минимальный процент выгоды от средней цены рынка (от 5 до 70, например: <code>15</code>):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_discount_pct)
async def save_discount_pct(message: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    val = max(5, min(70, int(digits))) if digits else 10
    await db.update_user_field(message.from_user.id, "min_discount_pct", val)
    await state.clear()
    await message.answer(f"✅ Порог выгоды установлен: <b>{val}%</b>.", parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data == "set_quiet_hours")
async def ask_quiet_hours(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_quiet_hours)
    await callback.message.answer(
        "🌙 Введите интервал тихих часов в формате <code>23:00-08:00</code> (или <code>-</code> чтобы отключить):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_quiet_hours)
async def save_quiet_hours(message: Message, state: FSMContext) -> None:
    txt = (message.text or "").strip()
    val = None if txt in ("-", "0", "off") else txt
    await db.update_user_field(message.from_user.id, "quiet_hours", val)
    await state.clear()
    await message.answer("✅ Настройка тихих часов сохранена!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "set_templates_menu")
async def open_templates_menu(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    text = (
        "💬 <b>Шаблоны сообщений (с поддержкой спинтакса)</b>\n\n"
        f"1️⃣ <b>Основной (используется в автоотклике):</b>\n<i>{html.escape(u.get('default_template') or '')}</i>\n\n"
        f"2️⃣ <b>С торгом (-10%):</b>\n<i>{html.escape(u.get('bargain_template') or '')}</i>\n\n"
        f"3️⃣ <b>Доставка:</b>\n<i>{html.escape(u.get('delivery_template') or '')}</i>\n\n"
        "💡 <i>Переменные: <code>{title}</code>, <code>{price}</code>, <code>{price_bargain}</code>.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=templates_menu_kb())
    await callback.answer()


@router.callback_query(F.data.in_({"set_tpl_main", "set_tpl_bargain", "set_tpl_delivery"}))
async def ask_template_edit(callback: CallbackQuery, state: FSMContext) -> None:
    mapping = {
        "set_tpl_main": (SettingsStates.waiting_tpl_main, "основной (для автоотклика)"),
        "set_tpl_bargain": (SettingsStates.waiting_tpl_bargain, "для торга"),
        "set_tpl_delivery": (SettingsStates.waiting_tpl_delivery, "про Авито Доставку"),
    }
    st, label = mapping[callback.data]
    await state.set_state(st)
    await callback.message.answer(f"✏️ Введите новый шаблон ({label}):", reply_markup=cancel_kb())
    await callback.answer()


@router.message(SettingsStates.waiting_tpl_main)
async def save_tpl_main(message: Message, state: FSMContext) -> None:
    if message.text:
        await db.update_user_field(message.from_user.id, "default_template", message.text.strip())
    await state.clear()
    await message.answer("✅ Основной шаблон обновлён!", reply_markup=main_menu_kb())


@router.message(SettingsStates.waiting_tpl_bargain)
async def save_tpl_bargain(message: Message, state: FSMContext) -> None:
    if message.text:
        await db.update_user_field(message.from_user.id, "bargain_template", message.text.strip())
    await state.clear()
    await message.answer("✅ Шаблон с торгом обновлён!", reply_markup=main_menu_kb())


@router.message(SettingsStates.waiting_tpl_delivery)
async def save_tpl_delivery(message: Message, state: FSMContext) -> None:
    if message.text:
        await db.update_user_field(message.from_user.id, "delivery_template", message.text.strip())
    await state.clear()
    await message.answer("✅ Шаблон про доставку обновлён!", reply_markup=main_menu_kb())


@router.callback_query(F.data == "set_blacklist_menu")
async def open_blacklist_menu(callback: CallbackQuery) -> None:
    bl = await db.get_blacklist(callback.from_user.id)
    if not bl:
        await callback.answer("Чёрный список продавцов пуст", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=f"♻️ Разблокировать: {sid}", callback_data=f"unban:{sid}")] for sid in bl[:15]]
    rows.append([InlineKeyboardButton(text="⬅️ Назад в настройки", callback_data="set_menu")])
    await callback.message.edit_text(
        "🚫 <b>Чёрный список продавцов:</b>\nНажмите на продавца, чтобы вернуть его в выдачу.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("unban:"))
async def unban_seller(callback: CallbackQuery) -> None:
    sid = callback.data.split(":", 1)[1]
    await db.remove_from_blacklist(callback.from_user.id, sid)
    await callback.answer("Продавец удалён из ЧС")
    await open_blacklist_menu(callback)


@router.message(F.text == "⭐ Избранное")
async def show_favorites(message: Message) -> None:
    favs = await db.get_favorites(message.from_user.id)
    if not favs:
        await message.answer("⭐ Избранное пока пусто. Нажимайте <b>«⭐ В избранное»</b> под интересными объявлениями.", parse_mode="HTML")
        return

    lines = ["⭐ <b>Сохранённые лоты:</b>\n"]
    rows = []
    for f in favs:
        p = f"{f['price']:,} ₽".replace(",", " ") if f.get("price") else "Цена не указана"
        lines.append(f"• <a href=\"{html.escape(f['url'])}\">{html.escape(f['title'])}</a> — <b>{p}</b>")
        rows.append([InlineKeyboardButton(text=f"❌ Убрать: {f['title'][:25]}", callback_data=f"fav_del:{f['id']}")])

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("fav_del:"))
async def delete_favorite_item(callback: CallbackQuery) -> None:
    fav_id = int(callback.data.split(":", 1)[1])
    await db.remove_favorite(fav_id, callback.from_user.id)
    await callback.answer("Удалено из избранного")
    await callback.message.delete()
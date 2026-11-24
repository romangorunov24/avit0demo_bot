import asyncio
import html
import json
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from bot.keyboards import (
    avito_optional_kb,
    buyer_settings_kb,
    cancel_kb,
    main_menu_kb,
    templates_menu_kb,
)
from bot.states import SettingsStates
from config import settings
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies

router = Router()


def _format_settings_summary(u: dict) -> str:
    status = "⏸ На паузе" if u.get("is_paused") else "🟢 Активен"
    proxy_state = "🟢 Подключён" if settings.PROXY_URL else "⚪️ Не задан"
    has_acc = bool(normalize_cookies(u.get("avito_cookies") or ""))
    mode = "🤖 Гибрид (1-клик + Автоотклик)" if (has_acc and u.get("auto_reply_enabled")) else "🛡 Безопасный 1-клик переход в Avito"

    return (
        "⚙️ <b>Центр управления и автоматизации</b>\n\n"
        f"• Мониторинг: <b>{status}</b> (интервал {settings.CHECK_INTERVAL_SEC} сек.)\n"
        f"• Режим работы: <b>{mode}</b>\n"
        f"• Мобильный прокси: {proxy_state}\n\n"
        "Настройте фильтры, ночной режим и быстрые шаблоны под себя:"
    )


@router.message(F.text == "⚙️ Настройки и Автоматизация")
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
    await callback.answer("Мониторинг поставлен на паузу" if new_val else "Мониторинг возобновлён")


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
        "📉 Введите минимальный процент выгоды от средней цены рынка (число от 5 до 70, например: <code>15</code>):",
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
    await message.answer(f"✅ Минимальный порог выгоды установлен: <b>{val}%</b>.", parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data == "set_quiet_hours")
async def ask_quiet_hours(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsStates.waiting_quiet_hours)
    await callback.message.answer(
        "🌙 Введите интервал тихих часов в формате <code>23:00-08:00</code> (уведомления будут приходить без звука)\n"
        "Или отправьте <code>-</code> чтобы отключить тихие часы:",
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
        "💬 <b>Ваши шаблоны быстрого отклика</b>\n\n"
        f"1️⃣ <b>Основной:</b>\n<i>{html.escape(u.get('default_template') or '')}</i>\n\n"
        f"2️⃣ <b>С торгом:</b>\n<i>{html.escape(u.get('bargain_template') or '')}</i>\n\n"
        f"3️⃣ <b>Доставка:</b>\n<i>{html.escape(u.get('delivery_template') or '')}</i>\n\n"
        "💡 <i>Доступны спинтакс <code>{Привет|Здравствуйте}</code> и переменные <code>{title}</code>, <code>{price}</code>, <code>{price_bargain}</code>.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=templates_menu_kb())
    await callback.answer()


@router.callback_query(F.data.in_({"set_tpl_main", "set_tpl_bargain", "set_tpl_delivery"}))
async def ask_template_edit(callback: CallbackQuery, state: FSMContext) -> None:
    mapping = {
        "set_tpl_main": (SettingsStates.waiting_tpl_main, "основной"),
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
        await message.answer("⭐ Список избранного пока пуст. Нажимайте <b>«⭐ В избранное»</b> под интересными лотами.", parse_mode="HTML")
        return

    lines = ["⭐ <b>Сохранённые объявления:</b>\n"]
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


# --- Опциональное подключение сессии Avito (для продвинутых покупателей) ---
@router.callback_query(F.data == "set_avito_menu")
async def open_avito_optional_menu(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    has_c = bool(normalize_cookies(u.get("avito_cookies") or ""))
    auto_on = bool(u.get("auto_reply_enabled"))
    status = "🟢 Привязана" if has_c else "⚪️ Не привязана"

    text = (
        "🔌 <b>Опциональный автоотклик через сессию Avito</b>\n\n"
        f"Статус сессии: <b>{status}</b>\n\n"
        "⚠️ <i>Используйте только технический аккаунт, вход в который выполнен через тот же прокси, что указан в боте, "
        "чтобы избежать сброса пароля антифродом Авито.</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=avito_optional_kb(has_c, auto_on))
    await callback.answer()


@router.callback_query(F.data == "acc_toggle_auto")
async def toggle_auto_reply_opt(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    new_val = 0 if u.get("auto_reply_enabled") else 1
    await db.update_user_field(callback.from_user.id, "auto_reply_enabled", new_val)
    await open_avito_optional_menu(callback)


@router.callback_query(F.data.in_({"acc_connect_pc", "acc_connect_mobile"}))
async def start_connect_cookies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SettingsStates.waiting_cookies)
    await callback.message.answer(
        "🔑 Отправьте JSON из расширения <b>Cookie-Editor</b> (файлом <code>cookies.json</code> или вставьте текстом):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(SettingsStates.waiting_cookies)
async def save_optional_cookies(message: Message, state: FSMContext) -> None:
    raw_text = ""
    if message.document:
        file = await message.bot.get_file(message.document.file_id)
        downloaded = await message.bot.download_file(file.file_path)
        raw_text = downloaded.read().decode("utf-8", errors="ignore")
    elif message.text:
        raw_text = message.text

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
        await message.answer("❌ Ключи <code>sessid</code> и <code>u</code> не найдены. Попробуйте снова:", parse_mode="HTML", reply_markup=cancel_kb())
        return

    await db.update_user_field(message.from_user.id, "avito_cookies", json.dumps(acc, ensure_ascii=False))
    await state.clear()
    await message.answer(f"✅ Сессия сохранена (ключи: <code>{', '.join(acc.keys())}</code>).", parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data == "acc_check")
async def check_optional_session(callback: CallbackQuery) -> None:
    u = await db.get_user_settings(callback.from_user.id)
    messenger = AvitoMessenger()
    _, info = await messenger.check_session(u.get("avito_cookies"))
    await callback.answer(info[:190], show_alert=True)


@router.callback_query(F.data == "acc_disconnect")
async def disconnect_optional_session(callback: CallbackQuery) -> None:
    await db.update_user_field(callback.from_user.id, "avito_cookies", None)
    await db.update_user_field(callback.from_user.id, "auto_reply_enabled", 0)
    await callback.answer("Аккаунт отвязан")
    await open_avito_optional_menu(callback)
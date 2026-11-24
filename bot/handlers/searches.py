import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import cancel_kb, main_menu_kb, search_detail_kb, searches_list_kb, skip_or_cancel_kb
from bot.states import SearchStates
from database import db
from services.worker import process_single_search

router = Router()


def _format_search_detail(s: dict) -> str:
    status = "🟢 Активен" if s.get("is_active") else "⏸ На паузе"
    min_p = f"{s['min_price']:,} ₽".replace(",", " ") if s.get("min_price") else "нет"
    max_p = f"{s['max_price']:,} ₽".replace(",", " ") if s.get("max_price") else "нет"
    sniper_p = f"{s['sniper_price']:,} ₽".replace(",", " ") if s.get("sniper_price") else "не задана"
    plus_w = html.escape(s.get("plus_words") or "нет")
    stop_w = html.escape(s.get("stop_words") or "нет")
    tpl = html.escape(s.get("message_template") or "Общий шаблон из настроек")
    sf_map = {"all": "Все", "private": "Только частники", "company": "Только магазины"}
    sf = sf_map.get(s.get("seller_filter") or "all", "Все")

    return (
        f"🔍 <b>Поиск: {html.escape(s['name'])}</b>\n\n"
        f"• Статус: {status}\n"
        f"• Диапазон цен: от <b>{min_p}</b> до <b>{max_p}</b>\n"
        f"• 🚨 Снайпер-цена: <b>{sniper_p}</b>\n"
        f"• ✅ Плюс-слова: <code>{plus_w}</code>\n"
        f"• 🚫 Стоп-слова: <code>{stop_w}</code>\n"
        f"• 👤 Продавцы: <b>{sf}</b>\n"
        f"• 💬 Шаблон: <i>{tpl}</i>\n"
        f"• 🔗 Ссылка: {html.escape(s['url'])}"
    )


@router.message(F.text == "🔍 Мои поиски")
async def list_searches(message: Message, state: FSMContext) -> None:
    await state.clear()
    searches = await db.get_user_searches(message.from_user.id)
    if not searches:
        await message.answer(
            "У вас пока нет активных поисков. Нажмите <b>«➕ Добавить поиск»</b>.",
            parse_mode="HTML",
            reply_markup=searches_list_kb([]),
        )
        return
    await message.answer("📋 <b>Ваши поиски (нажмите для настройки):</b>", parse_mode="HTML", reply_markup=searches_list_kb(searches))


@router.callback_query(F.data == "back_searches")
async def back_to_searches(callback: CallbackQuery) -> None:
    searches = await db.get_user_searches(callback.from_user.id)
    await callback.message.edit_text("📋 <b>Ваши поиски:</b>", parse_mode="HTML", reply_markup=searches_list_kb(searches))
    await callback.answer()


@router.message(F.text == "➕ Добавить поиск")
async def start_add_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SearchStates.waiting_name)
    await message.answer("1️⃣ Введите название поиска (например: <i>iPhone 15 Pro СПб</i>):", parse_mode="HTML", reply_markup=cancel_kb())


@router.callback_query(F.data == "add_search")
async def cb_add_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SearchStates.waiting_name)
    await callback.message.answer("1️⃣ Введите название поиска (например: <i>iPhone 15 Pro СПб</i>):", parse_mode="HTML", reply_markup=cancel_kb())
    await callback.answer()


@router.message(SearchStates.waiting_name)
async def step_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    await state.update_data(name=message.text.strip())
    await state.set_state(SearchStates.waiting_url)
    await message.answer("2️⃣ Отправьте ссылку на поиск с сайта <b>avito.ru</b>:", parse_mode="HTML", reply_markup=cancel_kb())


@router.message(SearchStates.waiting_url)
async def step_url(message: Message, state: FSMContext) -> None:
    if not message.text or "avito.ru" not in message.text:
        await message.answer("❌ Нужна корректная ссылка на avito.ru. Попробуйте снова:", reply_markup=cancel_kb())
        return
    await state.update_data(url=message.text.strip())
    await state.set_state(SearchStates.waiting_min_price)
    await message.answer("3️⃣ Минимальная цена в рублях (отсекает чехлы и хлам):", reply_markup=skip_or_cancel_kb("skip_min_price"))


@router.callback_query(F.data == "skip_min_price", SearchStates.waiting_min_price)
async def skip_min(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(min_price=None)
    await state.set_state(SearchStates.waiting_max_price)
    await callback.message.answer("4️⃣ Максимальная цена в рублях:", reply_markup=skip_or_cancel_kb("skip_max_price"))
    await callback.answer()


@router.message(SearchStates.waiting_min_price)
async def step_min(message: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    await state.update_data(min_price=int(digits) if digits else None)
    await state.set_state(SearchStates.waiting_max_price)
    await message.answer("4️⃣ Максимальная цена в рублях:", reply_markup=skip_or_cancel_kb("skip_max_price"))


@router.callback_query(F.data == "skip_max_price", SearchStates.waiting_max_price)
async def skip_max(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(max_price=None)
    await state.set_state(SearchStates.waiting_sniper_price)
    await callback.message.answer("5️⃣ 🚨 Снайпер-цена (пометит лот как супер-выгодный, если цена ниже этой суммы):", reply_markup=skip_or_cancel_kb("skip_sniper_price"))
    await callback.answer()


@router.message(SearchStates.waiting_max_price)
async def step_max(message: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    await state.update_data(max_price=int(digits) if digits else None)
    await state.set_state(SearchStates.waiting_sniper_price)
    await message.answer("5️⃣ 🚨 Снайпер-цена (пометит лот как супер-выгодный, если цена ниже этой суммы):", reply_markup=skip_or_cancel_kb("skip_sniper_price"))


@router.callback_query(F.data == "skip_sniper_price", SearchStates.waiting_sniper_price)
async def skip_sniper(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sniper_price=None)
    await state.set_state(SearchStates.waiting_plus_words)
    await callback.message.answer("6️⃣ ✅ Обязательные плюс-слова через запятую (например: <i>256, коробка, чек</i>):", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_plus_words"))
    await callback.answer()


@router.message(SearchStates.waiting_sniper_price)
async def step_sniper(message: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    await state.update_data(sniper_price=int(digits) if digits else None)
    await state.set_state(SearchStates.waiting_plus_words)
    await message.answer("6️⃣ ✅ Обязательные плюс-слова через запятую (например: <i>256, коробка, чек</i>):", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_plus_words"))


@router.callback_query(F.data == "skip_plus_words", SearchStates.waiting_plus_words)
async def skip_plus(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(plus_words=None)
    await state.set_state(SearchStates.waiting_stop_words)
    await callback.message.answer("7️⃣ 🚫 Стоп-слова через запятую (например: <i>разбит, на запчасти, копия</i>):", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_stop_words"))
    await callback.answer()


@router.message(SearchStates.waiting_plus_words)
async def step_plus(message: Message, state: FSMContext) -> None:
    await state.update_data(plus_words=(message.text or "").strip() or None)
    await state.set_state(SearchStates.waiting_stop_words)
    await message.answer("7️⃣ 🚫 Стоп-слова через запятую (например: <i>разбит, на запчасти, копия</i>):", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_stop_words"))


@router.callback_query(F.data == "skip_stop_words", SearchStates.waiting_stop_words)
async def finish_skip_stop(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await db.add_search(
        user_id=callback.from_user.id,
        name=data["name"],
        url=data["url"],
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        sniper_price=data.get("sniper_price"),
        plus_words=data.get("plus_words"),
        stop_words=None,
    )
    await state.clear()
    await callback.message.answer(f"✅ Поиск <b>«{html.escape(data['name'])}»</b> создан и запущен!", parse_mode="HTML", reply_markup=main_menu_kb())
    await callback.answer()


@router.message(SearchStates.waiting_stop_words)
async def finish_with_stop(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await db.add_search(
        user_id=message.from_user.id,
        name=data["name"],
        url=data["url"],
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        sniper_price=data.get("sniper_price"),
        plus_words=data.get("plus_words"),
        stop_words=(message.text or "").strip() or None,
    )
    await state.clear()
    await message.answer(f"✅ Поиск <b>«{html.escape(data['name'])}»</b> создан и запущен!", parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("sview_"))
async def open_search_detail(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_by_id(search_id)
    if not s:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.message.edit_text(
        _format_search_detail(s),
        parse_mode="HTML",
        reply_markup=search_detail_kb(search_id, bool(s["is_active"]), s.get("seller_filter") or "all"),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stoggle_"))
async def toggle_search(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_by_id(search_id)
    if s:
        new_val = 0 if s["is_active"] else 1
        await db.update_search_field(search_id, "is_active", new_val)
        s["is_active"] = new_val
        await callback.message.edit_text(
            _format_search_detail(s),
            parse_mode="HTML",
            reply_markup=search_detail_kb(search_id, bool(s["is_active"]), s.get("seller_filter") or "all"),
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("srun_"))
async def run_search_now(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_by_id(search_id)
    if not s:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.answer("⏳ Запускаю мгновенную проверку...")
    found = await process_single_search(callback.bot, s, force_preview=True)
    if found == 0:
        await callback.message.answer("⚠️ По этому поиску сейчас нет подходящих объявлений или IP прокси в лимите 429.")


@router.callback_query(F.data.startswith("sedit_"))
async def edit_search_param(callback: CallbackQuery, state: FSMContext) -> None:
    _, field, sid_str = callback.data.split("_", 2)
    search_id = int(sid_str)
    s = await db.get_search_by_id(search_id)
    if not s:
        await callback.answer("Поиск не найден", show_alert=True)
        return

    if field == "seller":
        order = ["all", "private", "company"]
        cur = s.get("seller_filter") or "all"
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "all"
        await db.update_search_field(search_id, "seller_filter", nxt)
        s["seller_filter"] = nxt
        await callback.message.edit_text(
            _format_search_detail(s),
            parse_mode="HTML",
            reply_markup=search_detail_kb(search_id, bool(s["is_active"]), nxt),
            disable_web_page_preview=True,
        )
        await callback.answer("Фильтр продавцов переключён")
        return

    prompts = {
        "price": "💰 Введите диапазон цен через дефис (например: <code>10000-45000</code>, или <code>0</code> чтобы сбросить):",
        "sniper": "🚨 Введите снайпер-цену в рублях (или <code>0</code> чтобы отключить):",
        "plus": "✅ Введите обязательные плюс-слова через запятую (или <code>-</code> чтобы очистить):",
        "stop": "🚫 Введите стоп-слова через запятую (или <code>-</code> чтобы очистить):",
        "tpl": "💬 Введите индивидуальный шаблон сообщения для этого поиска (поддерживается спинтакс и <code>{price_bargain}</code>, или <code>-</code> для сброса):",
        "name": "✏️ Введите новое название для этого поиска:",
    }
    await state.set_state(SearchStates.waiting_edit_field)
    await state.update_data(edit_sid=search_id, edit_field=field)
    await callback.message.answer(prompts[field], parse_mode="HTML", reply_markup=cancel_kb())
    await callback.answer()


@router.message(SearchStates.waiting_edit_field)
async def save_edited_search_param(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    search_id = data.get("edit_sid")
    field = data.get("edit_field")
    txt = (message.text or "").strip()

    if search_id and field and txt:
        if field == "price":
            if txt == "0":
                await db.update_search_field(search_id, "min_price", None)
                await db.update_search_field(search_id, "max_price", None)
            elif "-" in txt:
                p1, p2 = txt.split("-", 1)
                d1 = "".join(c for c in p1 if c.isdigit())
                d2 = "".join(c for c in p2 if c.isdigit())
                await db.update_search_field(search_id, "min_price", int(d1) if d1 else None)
                await db.update_search_field(search_id, "max_price", int(d2) if d2 else None)
            else:
                d = "".join(c for c in txt if c.isdigit())
                await db.update_search_field(search_id, "max_price", int(d) if d else None)
        elif field == "sniper":
            d = "".join(c for c in txt if c.isdigit())
            val = int(d) if d and int(d) > 0 else None
            await db.update_search_field(search_id, "sniper_price", val)
        elif field == "plus":
            await db.update_search_field(search_id, "plus_words", None if txt == "-" else txt)
        elif field == "stop":
            await db.update_search_field(search_id, "stop_words", None if txt == "-" else txt)
        elif field == "tpl":
            await db.update_search_field(search_id, "message_template", None if txt == "-" else txt)
        elif field == "name":
            await db.update_search_field(search_id, "name", txt)

    await state.clear()
    await message.answer("✅ Настройки поиска обновлены!", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("sdel_"))
async def del_search(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    await db.delete_search(search_id)
    searches = await db.get_user_searches(callback.from_user.id)
    await callback.message.edit_text("🗑 Поиск удалён.", reply_markup=searches_list_kb(searches))
    await callback.answer()
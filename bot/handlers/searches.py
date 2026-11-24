from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import cancel_kb, main_menu_kb, search_detail_kb, searches_list_kb, skip_or_cancel_kb
from bot.states import SearchStates
from database import db

router = Router()


def _format_search_detail(s: dict) -> str:
    status = "🟢 Активен" if s.get("is_active") else "⏸ На паузе"
    min_p = f"{s['min_price']} ₽" if s.get("min_price") else "нет"
    max_p = f"{s['max_price']} ₽" if s.get("max_price") else "нет"
    stop_w = s.get("stop_words") or "нет"
    return (
        f"🔍 <b>Поиск: {s['name']}</b>\n\n"
        f"Статус: {status}\n"
        f"Цена: от <b>{min_p}</b> до <b>{max_p}</b>\n"
        f"Стоп-слова: <code>{stop_w}</code>\n"
        f"Ссылка: {s['url']}"
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
    await message.answer("📋 <b>Ваши поиски:</b>", parse_mode="HTML", reply_markup=searches_list_kb(searches))


@router.callback_query(F.data == "back_searches")
async def back_to_searches(callback: CallbackQuery) -> None:
    searches = await db.get_user_searches(callback.from_user.id)
    await callback.message.edit_text("📋 <b>Ваши поиски:</b>", parse_mode="HTML", reply_markup=searches_list_kb(searches))
    await callback.answer()


@router.message(F.text == "➕ Добавить поиск")
async def start_add_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SearchStates.waiting_name)
    await message.answer("1️⃣ Введите название поиска (например: <i>iPhone 15 СПб</i>):", parse_mode="HTML", reply_markup=cancel_kb())


@router.callback_query(F.data == "add_search")
async def cb_add_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(SearchStates.waiting_name)
    await callback.message.answer("1️⃣ Введите название поиска (например: <i>iPhone 15 СПб</i>):", parse_mode="HTML", reply_markup=cancel_kb())
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
    await message.answer("3️⃣ Минимальная цена в рублях (числом):", reply_markup=skip_or_cancel_kb("skip_min_price"))


@router.callback_query(F.data == "skip_min_price", SearchStates.waiting_min_price)
async def skip_min(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(min_price=None)
    await state.set_state(SearchStates.waiting_max_price)
    await callback.message.answer("4️⃣ Максимальная цена в рублях (числом):", reply_markup=skip_or_cancel_kb("skip_max_price"))
    await callback.answer()


@router.message(SearchStates.waiting_min_price)
async def step_min(message: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    await state.update_data(min_price=int(digits) if digits else None)
    await state.set_state(SearchStates.waiting_max_price)
    await message.answer("4️⃣ Максимальная цена в рублях (числом):", reply_markup=skip_or_cancel_kb("skip_max_price"))


@router.callback_query(F.data == "skip_max_price", SearchStates.waiting_max_price)
async def skip_max(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(max_price=None)
    await state.set_state(SearchStates.waiting_stop_words)
    await callback.message.answer("5️⃣ Стоп-слова через запятую (например: <i>разбит, на запчасти, копия</i>):", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_stop_words"))
    await callback.answer()


@router.message(SearchStates.waiting_max_price)
async def step_max(message: Message, state: FSMContext) -> None:
    digits = "".join(c for c in (message.text or "") if c.isdigit())
    await state.update_data(max_price=int(digits) if digits else None)
    await state.set_state(SearchStates.waiting_stop_words)
    await message.answer("5️⃣ Стоп-слова через запятую (например: <i>разбит, на запчасти, копия</i>):", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_stop_words"))


@router.callback_query(F.data == "skip_stop_words", SearchStates.waiting_stop_words)
async def finish_skip_stop(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await db.add_search(
        user_id=callback.from_user.id,
        name=data["name"],
        url=data["url"],
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        stop_words=None,
        message_template=None,
    )
    await state.clear()
    await callback.message.answer(f"✅ Поиск <b>«{data['name']}»</b> создан и запущен!", parse_mode="HTML", reply_markup=main_menu_kb())
    await callback.answer()


@router.message(SearchStates.waiting_stop_words)
async def finish_with_stop(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    stop_words = (message.text or "").strip() or None
    await db.add_search(
        user_id=message.from_user.id,
        name=data["name"],
        url=data["url"],
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        stop_words=stop_words,
        message_template=None,
    )
    await state.clear()
    await message.answer(f"✅ Поиск <b>«{data['name']}»</b> создан и запущен!", parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("search_"))
async def open_search_detail(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_by_id(search_id)
    if not s:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.message.edit_text(
        _format_search_detail(s),
        parse_mode="HTML",
        reply_markup=search_detail_kb(search_id, bool(s["is_active"]), False),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_search_"))
async def toggle_search(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[2])
    s = await db.get_search_by_id(search_id)
    if s:
        new_val = 0 if s["is_active"] else 1
        await db.update_search_field(search_id, "is_active", new_val)
        s["is_active"] = new_val
        await callback.message.edit_text(
            _format_search_detail(s),
            parse_mode="HTML",
            reply_markup=search_detail_kb(search_id, bool(s["is_active"]), False),
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("del_search_"))
async def del_search(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[2])
    await db.delete_search(search_id)
    searches = await db.get_user_searches(callback.from_user.id)
    await callback.message.edit_text("🗑 Поиск удалён.", reply_markup=searches_list_kb(searches))
    await callback.answer()

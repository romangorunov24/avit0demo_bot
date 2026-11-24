from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import cancel_kb, search_detail_kb, searches_list_kb
from bot.states import SearchStates
from database import models
from utils.helpers import normalize_avito_url

router = Router()


def _format_search_card(s: dict) -> str:
    status = "🟢 Активен" if s["is_active"] else "⏸ На паузе"
    price_range = (
        f"от {s['min_price']} ₽ до {s['max_price']} ₽"
        if (s["min_price"] or s["max_price"])
        else "Любая"
    )
    sniper = (
        f"до {s['sniper_price']} ₽"
        if s["sniper_price"] > 0
        else "Всем подходящим (без порога)"
    )
    stop_w = s["stop_words"] if s["stop_words"] else "—"
    plus_w = s["plus_words"] if s["plus_words"] else "—"
    priv = "Да" if s["only_private"] else "Нет"

    return (
        f"<b>🔍 Поиск: {s['name']}</b>\n"
        f"• <b>Статус:</b> {status}\n"
        f"• <b>Фильтр цены:</b> {price_range}\n"
        f"• <b>Автоответ «Снайпер»:</b> {sniper}\n"
        f"• <b>Минус-слова:</b> <code>{stop_w}</code>\n"
        f"• <b>Плюс-слова:</b> <code>{plus_w}</code>\n"
        f"• <b>Только частники:</b> {priv}\n"
        f"• <b>Ссылка:</b> <a href=\"{s['url']}\">Открыть поиск</a>"
    )


@router.callback_query(F.data == "searches:list")
async def cb_searches_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    searches = await models.get_searches()
    text = (
        "<b>📋 Ваши задачи мониторинга</b>\n\nНажмите на поиск, чтобы настроить фильтры и автоответ:"
        if searches
        else "У вас пока нет активных поисков. Нажмите кнопку ниже, чтобы добавить первый."
    )
    await callback.message.edit_text(text, reply_markup=searches_list_kb(searches), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "searches:add")
async def cb_add_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchStates.waiting_name)
    await callback.message.edit_text(
        "<b>Шаг 1/2.</b> Введите название для поиска (например: <i>iPhone 13 Pro Max Москва</i>):",
        reply_markup=cancel_kb("searches:list"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SearchStates.waiting_name)
async def msg_search_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Введите корректное название (минимум 2 символа):")
        return
    await state.update_data(name=name)
    await state.set_state(SearchStates.waiting_url)
    await message.answer(
        "<b>Шаг 2/2.</b> Отправьте ссылку с Авито (выберите нужную категорию, город и параметры на сайте, затем скопируйте URL из адресной строки):\n\n"
        "<i>Сортировку по новизне бот подставит автоматически.</i>",
        reply_markup=cancel_kb("searches:list"),
        parse_mode="HTML",
    )


@router.message(SearchStates.waiting_url)
async def msg_search_url(message: Message, state: FSMContext) -> None:
    try:
        clean_url = normalize_avito_url(message.text or "")
    except ValueError as e:
        await message.answer(f"❌ {e}\nПопробуйте отправить ссылку ещё раз:")
        return

    data = await state.get_data()
    search_id = await models.add_search(name=data["name"], url=clean_url)
    await state.clear()
    search = await models.get_search(search_id)
    await message.answer(
        "✅ Поиск создан! Настройте фильтры ниже:\n\n" + _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("search:view:"))
async def cb_search_view(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    sid = int(callback.data.split(":")[2])
    search = await models.get_search(sid)
    if not search:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.message.edit_text(
        _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("search:toggle:"))
async def cb_search_toggle(callback: CallbackQuery) -> None:
    sid = int(callback.data.split(":")[2])
    search = await models.get_search(sid)
    if not search:
        return
    new_val = 0 if search["is_active"] else 1
    await models.update_search_field(sid, "is_active", new_val)
    search = await models.get_search(sid)
    await callback.message.edit_text(
        _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer("Статус обновлен")


@router.callback_query(F.data.startswith("search:private:"))
async def cb_search_private(callback: CallbackQuery) -> None:
    sid = int(callback.data.split(":")[2])
    search = await models.get_search(sid)
    if not search:
        return
    new_val = 0 if search["only_private"] else 1
    await models.update_search_field(sid, "only_private", new_val)
    search = await models.get_search(sid)
    await callback.message.edit_text(
        _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer("Фильтр частников обновлен")


@router.callback_query(F.data.startswith("search:delete:"))
async def cb_search_delete(callback: CallbackQuery) -> None:
    sid = int(callback.data.split(":")[2])
    await models.delete_search(sid)
    searches = await models.get_searches()
    await callback.message.edit_text(
        "🗑 Поиск удален.\n\n<b>📋 Ваши задачи мониторинга:</b>",
        reply_markup=searches_list_kb(searches),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("search:price:"))
async def cb_search_price(callback: CallbackQuery, state: FSMContext) -> None:
    sid = int(callback.data.split(":")[2])
    await state.update_data(edit_sid=sid)
    await state.set_state(SearchStates.waiting_min_price)
    await callback.message.edit_text(
        "Введите <b>минимальную и максимальную</b> цену через пробел (например: <code>25000 45000</code>).\n"
        "Чтобы сбросить ограничение, отправьте <code>0 0</code>:",
        reply_markup=cancel_kb(f"search:view:{sid}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SearchStates.waiting_min_price)
async def msg_search_price(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").strip().split()
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await message.answer("Введите два числа через пробел, например: <code>20000 50000</code>", parse_mode="HTML")
        return
    data = await state.get_data()
    sid = data["edit_sid"]
    await models.update_search_field(sid, "min_price", int(parts[0]))
    await models.update_search_field(sid, "max_price", int(parts[1]))
    await state.clear()
    search = await models.get_search(sid)
    await message.answer(
        _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("search:sniper:"))
async def cb_search_sniper(callback: CallbackQuery, state: FSMContext) -> None:
    sid = int(callback.data.split(":")[2])
    await state.update_data(edit_sid=sid)
    await state.set_state(SearchStates.waiting_sniper_price)
    await callback.message.edit_text(
        "🎯 <b>Режим «Снайпер»</b>\n"
        "Укажите максимальную цену в рублях, при которой бот <b>автоматически напишет продавцу первым</b> "
        "(остальные объявления просто придут вам в уведомлении).\n\n"
        "Отправьте <code>0</code>, чтобы бот писал вообще по всем новым объявлениям из этого поиска:",
        reply_markup=cancel_kb(f"search:view:{sid}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SearchStates.waiting_sniper_price)
async def msg_search_sniper(message: Message, state: FSMContext) -> None:
    val = (message.text or "").strip()
    if not val.isdigit():
        await message.answer("Введите целое число (например: <code>35000</code> или <code>0</code>):", parse_mode="HTML")
        return
    data = await state.get_data()
    sid = data["edit_sid"]
    await models.update_search_field(sid, "sniper_price", int(val))
    await state.clear()
    search = await models.get_search(sid)
    await message.answer(
        _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("search:stop:"))
async def cb_search_stop(callback: CallbackQuery, state: FSMContext) -> None:
    sid = int(callback.data.split(":")[2])
    await state.update_data(edit_sid=sid)
    await state.set_state(SearchStates.waiting_stop_words)
    await callback.message.edit_text(
        "🚫 Введите <b>минус-слова</b> через запятую (например: <code>разбит, запчасти, icloud, копия, чехол</code>).\n"
        "Чтобы очистить список, отправьте <code>-</code>:",
        reply_markup=cancel_kb(f"search:view:{sid}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SearchStates.waiting_stop_words)
async def msg_search_stop(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    clean = "" if raw == "-" else ", ".join(w.strip().lower() for w in raw.split(",") if w.strip())
    data = await state.get_data()
    sid = data["edit_sid"]
    await models.update_search_field(sid, "stop_words", clean)
    await state.clear()
    search = await models.get_search(sid)
    await message.answer(
        _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("search:plus:"))
async def cb_search_plus(callback: CallbackQuery, state: FSMContext) -> None:
    sid = int(callback.data.split(":")[2])
    await state.update_data(edit_sid=sid)
    await state.set_state(SearchStates.waiting_plus_words)
    await callback.message.edit_text(
        "✅ Введите <b>обязательные плюс-слова</b> через запятую (объявление подойдет, если в нем есть хотя бы одно из слов, например: <code>оригинал, идеал, не вскрывался</code>).\n"
        "Чтобы очистить список, отправьте <code>-</code>:",
        reply_markup=cancel_kb(f"search:view:{sid}"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SearchStates.waiting_plus_words)
async def msg_search_plus(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    clean = "" if raw == "-" else ", ".join(w.strip().lower() for w in raw.split(",") if w.strip())
    data = await state.get_data()
    sid = data["edit_sid"]
    await models.update_search_field(sid, "plus_words", clean)
    await state.clear()
    search = await models.get_search(sid)
    await message.answer(
        _format_search_card(search),
        reply_markup=search_detail_kb(search),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

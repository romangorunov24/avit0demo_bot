import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import (
    cancel_kb,
    city_kb,
    confirm_delete_kb,
    main_menu_kb,
    memory_kb,
    search_detail_kb,
    searches_list_kb,
    skip_or_cancel_kb,
)
from bot.states import SearchStates
from config import settings
from database import db
from services.search_url import build_search_url, city_title, resolve_city, validate_avito_url
from services.worker import process_single_search

router = Router()

MAX_SEARCHES_PER_USER = 15  # у администратора без ограничения
MAX_NAME_LEN = 60
MAX_TEMPLATE_LEN = 1000
MAX_PRICE = 100_000_000


async def _searches_limit_reached(user_id: int) -> bool:
    if user_id in settings.admin_ids_list:
        return False
    return len(await db.get_user_searches(user_id)) >= MAX_SEARCHES_PER_USER


LIMIT_TEXT = f"Достигнут лимит: не больше {MAX_SEARCHES_PER_USER} поисков на пользователя. Удалите ненужный поиск в «🔍 Мои поиски»."


def _parse_price(text: str | None) -> tuple[int | None, bool]:
    """(значение, корректно). Пустой ввод = не задано (корректно); текст без цифр = некорректно."""
    raw = (text or "").strip()
    if not raw:
        return None, True
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None, False
    return min(int(digits), MAX_PRICE), True


def _format_search_detail(s: dict) -> str:
    status = "🟢 Активен" if s.get("is_active") else "⏸ На паузе"
    auto_st = "🤖 ВКЛ (пишет сам)" if s.get("auto_reply", 1) else "⚪️ ВЫКЛ (только уведомления)"
    min_p = f"{s['min_price']:,} ₽".replace(",", " ") if s.get("min_price") else "не задана"
    max_p = f"{s['max_price']:,} ₽".replace(",", " ") if s.get("max_price") else "не задана"
    sniper_p = f"{s['sniper_price']:,} ₽".replace(",", " ") if s.get("sniper_price") else "не задана"
    plus_w = html.escape(s.get("plus_words") or "нет")
    stop_w = html.escape(s.get("stop_words") or "нет")
    tpl = html.escape(s.get("message_template") or "Общий шаблон из настроек")
    sf_map = {"all": "Все", "private": "Только частники", "company": "Только магазины"}
    sf = sf_map.get(s.get("seller_filter") or "all", "Все")

    return (
        f"🔍 <b>Поиск: {html.escape(s['name'])}</b>\n\n"
        f"• Мониторинг: {status}\n"
        f"• Автоотклик по поиску: <b>{auto_st}</b>\n"
        f"• Мин. цена: <b>{min_p}</b> | Макс. цена: <b>{max_p}</b>\n"
        f"• 🚨 Снайпер-цена: <b>{sniper_p}</b>\n"
        f"• ✅ Плюс-слова: <code>{plus_w}</code>\n"
        f"• 🚫 Стоп-слова: <code>{stop_w}</code>\n"
        f"• 👤 Продавцы: <b>{sf}</b>\n"
        f"• 💬 Шаблон: <i>{tpl}</i>\n"
        f"• 📍 Город: <b>{html.escape(city_title(s.get('city')))}</b>\n"
        f"• 💾 Память: <b>{html.escape((s.get('memory') + ' ГБ') if s.get('memory') else 'любая')}</b>\n"
        f"• 🔗 Ссылка: {html.escape(s['url'])}"
    )


@router.message(F.text == "🔍 Мои поиски")
async def list_searches(message: Message, state: FSMContext) -> None:
    await state.clear()
    searches = await db.get_user_searches(message.from_user.id)
    if not searches:
        await message.answer(
            "У вас пока нет активных поисков.\nНажмите <b>«➕ Добавить поиск»</b>, чтобы начать отслеживать лоты.",
            parse_mode="HTML",
            reply_markup=searches_list_kb([]),
        )
        return
    await message.answer(
        "📋 <b>Ваши поиски</b> (🟢 — активен, 🤖 — автоотклик включён):\nНажмите на поиск для гибкой настройки:",
        parse_mode="HTML",
        reply_markup=searches_list_kb(searches),
    )


@router.callback_query(F.data == "back_searches")
async def back_to_searches(callback: CallbackQuery) -> None:
    searches = await db.get_user_searches(callback.from_user.id)
    await callback.message.edit_text("📋 <b>Ваши поиски:</b>", parse_mode="HTML", reply_markup=searches_list_kb(searches))
    await callback.answer()


@router.message(F.text == "➕ Добавить поиск")
async def start_add_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    if await _searches_limit_reached(message.from_user.id):
        await message.answer(LIMIT_TEXT)
        return
    await state.set_state(SearchStates.waiting_name)
    await message.answer(
        "1️⃣ <b>Шаг 1 из 7 — Название поиска</b>\n\n"
        "Введите понятное название для себя (например: <i>iPhone 15 Pro 256</i> или <i>Видеокарты RTX</i>):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.callback_query(F.data == "add_search")
async def cb_add_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if await _searches_limit_reached(callback.from_user.id):
        await callback.answer(LIMIT_TEXT, show_alert=True)
        return
    await state.set_state(SearchStates.waiting_name)
    await callback.message.answer(
        "1️⃣ <b>Шаг 1 из 7 — Название поиска</b>\n\n"
        "Введите понятное название для себя (например: <i>iPhone 15 Pro 256</i>):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


PARAM_INTRO = (
    "🧭 <b>Поиск по параметрам — шаг 1 из 3: город</b>\n\n"
    "Выберите город, где искать объявления. Бот сам соберёт ссылку на Авито."
)


@router.message(F.text == "🧭 Поиск по параметрам")
async def start_param_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    if await _searches_limit_reached(message.from_user.id):
        await message.answer(LIMIT_TEXT)
        return
    await state.set_state(SearchStates.waiting_city)
    await message.answer(PARAM_INTRO, parse_mode="HTML", reply_markup=city_kb())


@router.callback_query(F.data == "city_other", SearchStates.waiting_city)
async def city_other(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Напишите название города (например: <i>Казань</i>). Если города нет в списке, "
        "используйте «➕ Добавить поиск» и вставьте ссылку с Авито.",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


async def _ask_model(target: Message, state: FSMContext, slug: str) -> None:
    await state.update_data(city=slug)
    await state.set_state(SearchStates.waiting_model)
    await target.answer(
        f"🧭 <b>Шаг 2 из 3: модель</b>\n\nГород: <b>{html.escape(city_title(slug))}</b>.\n"
        "Напишите марку и модель так, как набирали бы в поиске Авито (например: <i>iPhone 13 Pro Max</i>):",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.callback_query(F.data.startswith("city:"), SearchStates.waiting_city)
async def pick_city(callback: CallbackQuery, state: FSMContext) -> None:
    slug = callback.data.split(":", 1)[1]
    if resolve_city(slug) is None:
        await callback.answer("Неизвестный город", show_alert=True)
        return
    await _ask_model(callback.message, state, slug)
    await callback.answer()


@router.message(SearchStates.waiting_city)
async def type_city(message: Message, state: FSMContext) -> None:
    slug = resolve_city(message.text or "")
    if not slug:
        await message.answer(
            "Такого города нет в списке. Выберите кнопкой или используйте «➕ Добавить поиск» со ссылкой с Авито.",
            reply_markup=city_kb(),
        )
        return
    await _ask_model(message, state, slug)


@router.message(SearchStates.waiting_model)
async def step_model(message: Message, state: FSMContext) -> None:
    model = " ".join((message.text or "").split())
    if len(model) < 2:
        await message.answer("Введите название модели (минимум 2 символа):", reply_markup=cancel_kb())
        return
    await state.update_data(model=model[:80])
    await state.set_state(SearchStates.waiting_memory)
    await message.answer(
        "🧭 <b>Шаг 3 из 3: объём памяти</b>\n\nБот пропустит только объявления с этим объёмом в заголовке или описании.",
        parse_mode="HTML",
        reply_markup=memory_kb(),
    )


@router.callback_query(F.data.startswith("mem:"), SearchStates.waiting_memory)
async def pick_memory(callback: CallbackQuery, state: FSMContext) -> None:
    value = callback.data.split(":", 1)[1]
    memory = None if value == "any" else value
    data = await state.get_data()
    slug, model = data["city"], data["model"]
    mem_label = "" if not memory else (" 1 ТБ" if memory == "1024" else f" {memory} ГБ")
    name = f"{model}{mem_label} · {city_title(slug)}"[:60]
    await state.update_data(memory=memory, name=name, url=build_search_url(slug, model))
    await state.set_state(SearchStates.waiting_min_price)
    await callback.message.answer(
        f"✅ Поиск: <b>{html.escape(name)}</b>\n\n"
        "3️⃣ <b>Минимальная цена (в рублях)</b>\n\n"
        "Отсекает чехлы, коробки и фейки за 100 ₽. Введите число (например: <code>15000</code>) или пропустите:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_min_price"),
    )
    await callback.answer()


@router.message(SearchStates.waiting_name)
async def step_name(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    await state.update_data(name=message.text.strip()[:MAX_NAME_LEN])
    await state.set_state(SearchStates.waiting_url)
    await message.answer(
        "2️⃣ <b>Шаг 2 из 7 — Ссылка на выдачу Авито</b>\n\n"
        "Откройте <b>avito.ru</b>, выберите город, категорию и нужные параметры, затем скопируйте ссылку из адресной строки и отправьте сюда:",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )


@router.message(SearchStates.waiting_url)
async def step_url(message: Message, state: FSMContext) -> None:
    checked = validate_avito_url(message.text)
    if not checked:
        await message.answer("❌ Нужна корректная ссылка на avito.ru. Вставьте ссылку ещё раз:", reply_markup=cancel_kb())
        return
    await state.update_data(url=checked)
    await state.set_state(SearchStates.waiting_min_price)
    await message.answer(
        "3️⃣ <b>Шаг 3 из 7 — Минимальная цена (в рублях)</b>\n\n"
        "💡 <i>Зачем это нужно:</i> отсекает чехлы, коробки, разбитые экраны и фейки за 100 ₽.\n"
        "Введите число (например: <code>15000</code>) или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_min_price"),
    )


@router.callback_query(F.data == "skip_min_price", SearchStates.waiting_min_price)
async def skip_min(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(min_price=None)
    await state.set_state(SearchStates.waiting_max_price)
    await callback.message.answer(
        "4️⃣ <b>Шаг 4 из 7 — Максимальная цена (в рублях)</b>\n\n"
        "Введите потолок цены (например: <code>55000</code>) или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_max_price"),
    )
    await callback.answer()


@router.message(SearchStates.waiting_min_price)
async def step_min(message: Message, state: FSMContext) -> None:
    value, valid = _parse_price(message.text)
    if not valid:
        await message.answer("Введите сумму цифрами, например: <code>15000</code>, или нажмите «Пропустить».", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_min_price"))
        return
    await state.update_data(min_price=value)
    await state.set_state(SearchStates.waiting_max_price)
    await message.answer(
        "4️⃣ <b>Шаг 4 из 7 — Максимальная цена (в рублях)</b>\n\n"
        "Введите потолок цены (например: <code>55000</code>) или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_max_price"),
    )


@router.callback_query(F.data == "skip_max_price", SearchStates.waiting_max_price)
async def skip_max(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(max_price=None)
    await state.set_state(SearchStates.waiting_sniper_price)
    await callback.message.answer(
        "5️⃣ <b>Шаг 5 из 7 — Снайпер-цена (супер-выгода)</b>\n\n"
        "💡 <i>Зачем это нужно:</i> если выйдет лот дешевле этой суммы, бот пометит его как <b>🚨 СНАЙПЕР-ЦЕНА</b>.\n"
        "Введите сумму или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_sniper_price"),
    )
    await callback.answer()


@router.message(SearchStates.waiting_max_price)
async def step_max(message: Message, state: FSMContext) -> None:
    value, valid = _parse_price(message.text)
    if not valid:
        await message.answer("Введите сумму цифрами, например: <code>55000</code>, или нажмите «Пропустить».", parse_mode="HTML", reply_markup=skip_or_cancel_kb("skip_max_price"))
        return
    min_price = (await state.get_data()).get("min_price")
    if value and min_price and value < min_price:
        await message.answer(
            f"Максимальная цена не может быть меньше минимальной ({min_price} ₽). Введите другую сумму или нажмите «Пропустить».",
            reply_markup=skip_or_cancel_kb("skip_max_price"),
        )
        return
    await state.update_data(max_price=value)
    await state.set_state(SearchStates.waiting_sniper_price)
    await message.answer(
        "5️⃣ <b>Шаг 5 из 7 — Снайпер-цена (супер-выгода)</b>\n\n"
        "💡 <i>Зачем это нужно:</i> если выйдет лот дешевле этой суммы, бот пометит его как <b>🚨 СНАЙПЕР-ЦЕНА</b>.\n"
        "Введите сумму или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_sniper_price"),
    )


@router.callback_query(F.data == "skip_sniper_price", SearchStates.waiting_sniper_price)
async def skip_sniper(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(sniper_price=None)
    await state.set_state(SearchStates.waiting_plus_words)
    await callback.message.answer(
        "6️⃣ <b>Шаг 6 из 7 — Обязательные плюс-слова</b>\n\n"
        "Бот пропустит только объявления, где есть хотя бы одно из этих слов (через запятую, например: <i>256, чек, коробка</i>).\n"
        "Если не нужно — нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_plus_words"),
    )
    await callback.answer()


@router.message(SearchStates.waiting_sniper_price)
async def step_sniper(message: Message, state: FSMContext) -> None:
    value, valid = _parse_price(message.text)
    if not valid:
        await message.answer("Введите сумму цифрами или нажмите «Пропустить».", reply_markup=skip_or_cancel_kb("skip_sniper_price"))
        return
    await state.update_data(sniper_price=value)
    await state.set_state(SearchStates.waiting_plus_words)
    await message.answer(
        "6️⃣ <b>Шаг 6 из 7 — Обязательные плюс-слова</b>\n\n"
        "Бот пропустит только объявления, где есть хотя бы одно из этих слов (через запятую, например: <i>256, чек, коробка</i>).\n"
        "Если не нужно — нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_plus_words"),
    )


@router.callback_query(F.data == "skip_plus_words", SearchStates.waiting_plus_words)
async def skip_plus(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(plus_words=None)
    await state.set_state(SearchStates.waiting_stop_words)
    await callback.message.answer(
        "7️⃣ <b>Шаг 7 из 7 — Стоп-слова (фильтр мусора)</b>\n\n"
        "Объявления с этими словами будут игнорироваться и не получат автоотклик.\n"
        "Укажите через запятую (например: <i>разбит, на запчасти, копия, не включается</i>) или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_stop_words"),
    )
    await callback.answer()


@router.message(SearchStates.waiting_plus_words)
async def step_plus(message: Message, state: FSMContext) -> None:
    await state.update_data(plus_words=(message.text or "").strip() or None)
    await state.set_state(SearchStates.waiting_stop_words)
    await message.answer(
        "7️⃣ <b>Шаг 7 из 7 — Стоп-слова (фильтр мусора)</b>\n\n"
        "Объявления с этими словами будут игнорироваться и не получат автоотклик.\n"
        "Укажите через запятую (например: <i>разбит, на запчасти, копия, не включается</i>) или нажмите «Пропустить»:",
        parse_mode="HTML",
        reply_markup=skip_or_cancel_kb("skip_stop_words"),
    )


@router.callback_query(F.data == "skip_stop_words", SearchStates.waiting_stop_words)
async def finish_skip_stop(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if await _searches_limit_reached(callback.from_user.id):
        await state.clear()
        await callback.answer(LIMIT_TEXT, show_alert=True)
        return
    await db.add_search(
        user_id=callback.from_user.id,
        name=data["name"],
        url=data["url"],
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        sniper_price=data.get("sniper_price"),
        plus_words=data.get("plus_words"),
        stop_words=None,
        auto_reply=1,
        city=data.get("city"),
        memory=data.get("memory"),
    )
    await state.clear()
    await callback.message.answer(
        f"✅ Поиск <b>«{html.escape(data['name'])}»</b> создан и поставлен на мониторинг!\n"
        "Первый цикл запомнит текущие объявления, а на все новые лоты сразу придут уведомления (и сработает автоотклик, если он включён).",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.message(SearchStates.waiting_stop_words)
async def finish_with_stop(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if await _searches_limit_reached(message.from_user.id):
        await state.clear()
        await message.answer(LIMIT_TEXT, reply_markup=main_menu_kb())
        return
    await db.add_search(
        user_id=message.from_user.id,
        name=data["name"],
        url=data["url"],
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        sniper_price=data.get("sniper_price"),
        plus_words=data.get("plus_words"),
        stop_words=(message.text or "").strip() or None,
        auto_reply=1,
        city=data.get("city"),
        memory=data.get("memory"),
    )
    await state.clear()
    await message.answer(
        f"✅ Поиск <b>«{html.escape(data['name'])}»</b> создан и поставлен на мониторинг!\n"
        "Первый цикл запомнит текущие объявления, а на все новые лоты сразу придут уведомления (и сработает автоотклик, если он включён).",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data.startswith("sview_"))
async def open_search_detail(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_owned(search_id, callback.from_user.id)
    if not s:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.message.edit_text(
        _format_search_detail(s),
        parse_mode="HTML",
        reply_markup=search_detail_kb(
            search_id,
            bool(s["is_active"]),
            bool(s.get("auto_reply", 1)),
            s.get("seller_filter") or "all",
        ),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("stoggle_"))
async def toggle_search(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_owned(search_id, callback.from_user.id)
    if s:
        new_val = 0 if s["is_active"] else 1
        await db.update_search_field(search_id, "is_active", new_val)
        s["is_active"] = new_val
        await callback.message.edit_text(
            _format_search_detail(s),
            parse_mode="HTML",
            reply_markup=search_detail_kb(
                search_id,
                bool(s["is_active"]),
                bool(s.get("auto_reply", 1)),
                s.get("seller_filter") or "all",
            ),
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("sauto_"))
async def toggle_search_autoreply(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_owned(search_id, callback.from_user.id)
    if s:
        new_val = 0 if s.get("auto_reply", 1) else 1
        await db.update_search_field(search_id, "auto_reply", new_val)
        s["auto_reply"] = new_val
        await callback.message.edit_text(
            _format_search_detail(s),
            parse_mode="HTML",
            reply_markup=search_detail_kb(
                search_id,
                bool(s["is_active"]),
                bool(new_val),
                s.get("seller_filter") or "all",
            ),
            disable_web_page_preview=True,
        )
        await callback.answer("Автоотклик по этому поиску включён" if new_val else "Автоотклик по этому поиску выключен")
        return
    await callback.answer()


@router.callback_query(F.data.startswith("srun_"))
async def run_search_now(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_owned(search_id, callback.from_user.id)
    if not s:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.answer("⏳ Запускаю тестовую проверку без отправки сообщений...")
    found = await process_single_search(callback.bot, s, force_preview=True)
    if found == 0:
        await callback.message.answer(
            "⚠️ Подходящих объявлений не найдено.\n"
            "Возможные причины: фильтры (цена, память, слова) отсекли всю выдачу, по ссылке ничего нет или нет связи с Avito.\n"
            "Для диагностики сети нажмите <b>«🤖 Автоотклик и Аккаунт» → «🌐 Проверить IP и связь с Avito»</b>, "
            "подробности смотрите в консоли бота.",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("sedit_"))
async def edit_search_param(callback: CallbackQuery, state: FSMContext) -> None:
    _, field, sid_str = callback.data.split("_", 2)
    search_id = int(sid_str)
    s = await db.get_search_owned(search_id, callback.from_user.id)
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
            reply_markup=search_detail_kb(
                search_id,
                bool(s["is_active"]),
                bool(s.get("auto_reply", 1)),
                nxt,
            ),
            disable_web_page_preview=True,
        )
        await callback.answer("Фильтр продавцов переключён")
        return

    prompts = {
        "price": "💰 Введите диапазон цен через дефис (например: <code>15000-50000</code>, или <code>0</code> чтобы сбросить):",
        "sniper": "🚨 Введите снайпер-цену в рублях (или <code>0</code> чтобы отключить):",
        "plus": "✅ Введите обязательные плюс-слова через запятую (или <code>-</code> чтобы очистить):",
        "stop": "🚫 Введите стоп-слова через запятую (или <code>-</code> чтобы очистить):",
        "tpl": "💬 Введите свой шаблон автоотклика для этого поиска (поддерживается спинтакс и <code>{price_bargain}</code>, или <code>-</code> для сброса):",
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

    s = await db.get_search_owned(search_id, message.from_user.id) if search_id else None
    if not s:
        await state.clear()
        await message.answer("Поиск не найден.", reply_markup=main_menu_kb())
        return
    if not txt:
        await message.answer("Пришлите значение текстом.", reply_markup=cancel_kb())
        return

    if field == "price":
        if txt == "0":
            lo, hi = None, None
        elif "-" in txt:
            p1, p2 = txt.split("-", 1)
            (lo, ok1), (hi, ok2) = _parse_price(p1), _parse_price(p2)
            if not (ok1 and ok2) or (lo is None and hi is None):
                await message.answer("Не понял диапазон. Пример: <code>15000-50000</code>", parse_mode="HTML", reply_markup=cancel_kb())
                return
        else:
            lo, (hi, ok) = s.get("min_price"), _parse_price(txt)
            if not ok or hi is None:
                await message.answer("Введите число, диапазон <code>15000-50000</code> или <code>0</code> для сброса.", parse_mode="HTML", reply_markup=cancel_kb())
                return
        if lo and hi and lo > hi:
            lo, hi = hi, lo  # перепутали порядок: меняем местами
        await db.update_search_field(search_id, "min_price", lo)
        await db.update_search_field(search_id, "max_price", hi)
    elif field == "sniper":
        value, valid = _parse_price(txt)
        if not valid:
            await message.answer("Введите сумму цифрами или <code>0</code>, чтобы отключить.", parse_mode="HTML", reply_markup=cancel_kb())
            return
        await db.update_search_field(search_id, "sniper_price", value if value and value > 0 else None)
    elif field == "plus":
        await db.update_search_field(search_id, "plus_words", None if txt == "-" else txt)
    elif field == "stop":
        await db.update_search_field(search_id, "stop_words", None if txt == "-" else txt)
    elif field == "tpl":
        if len(txt) > MAX_TEMPLATE_LEN:
            await message.answer(f"Шаблон слишком длинный (максимум {MAX_TEMPLATE_LEN} символов).", reply_markup=cancel_kb())
            return
        await db.update_search_field(search_id, "message_template", None if txt == "-" else txt)
    elif field == "name":
        await db.update_search_field(search_id, "name", txt[:MAX_NAME_LEN])

    await state.clear()
    await message.answer("✅ Параметры поиска обновлены!", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("sdel_"))
async def ask_delete_search(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    s = await db.get_search_owned(search_id, callback.from_user.id)
    if not s:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.message.edit_text(
        f"🗑 Удалить поиск <b>«{html.escape(s['name'])}»</b>? Это действие нельзя отменить.",
        parse_mode="HTML",
        reply_markup=confirm_delete_kb(search_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sdelok_"))
async def del_search(callback: CallbackQuery) -> None:
    search_id = int(callback.data.split("_")[1])
    deleted = await db.delete_search(search_id, callback.from_user.id)
    searches = await db.get_user_searches(callback.from_user.id)
    await callback.message.edit_text("🗑 Поиск удалён." if deleted else "Поиск не найден.", reply_markup=searches_list_kb(searches))
    await callback.answer()

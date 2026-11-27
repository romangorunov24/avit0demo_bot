from __future__ import annotations

import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from avito.parser import build_search_url
from bot.keyboards import (
    cancel_fsm_kb,
    search_detail_kb,
    searches_list_kb,
)
from bot.states import AddSearchStates, EditSearchTemplateStates
from database.db import Database
from services.scheduler import AvitoMonitorService

router = Router()


def _format_search_card(task, default_tpl: str) -> str:
    status = "🟢 Активен" if task.is_active else "⏸ На паузе"
    ar = "💬 Включён" if task.auto_reply else "🔕 Выключен"
    price_str = "Любая"
    if task.min_price or task.max_price:
        p_min = f"от {task.min_price} ₽" if task.min_price else ""
        p_max = f"до {task.max_price} ₽" if task.max_price else ""
        price_str = f"{p_min} {p_max}".strip()

    tpl = task.reply_template.strip() or f"(Общий) {default_tpl}"
    inc = task.include_words or "нет"
    exc = task.exclude_words or "нет"

    return (
        f"🔍 <b>Поиск: {html.escape(task.name)}</b>\n\n"
        f"• <b>Статус:</b> {status}\n"
        f"• <b>Автоотклик:</b> {ar}\n"
        f"• <b>Цена:</b> {html.escape(price_str)}\n"
        f"• <b>Ключевые слова:</b> {html.escape(inc)}\n"
        f"• <b>Стоп-слова:</b> {html.escape(exc)}\n"
        f"• <b>Последняя проверка:</b> {task.last_checked_at or 'ещё не выполнялась'}\n"
        f"• <b>URL:</b> <a href=\"{html.escape(task.search_url)}\">Открыть выдачу</a>\n\n"
        f"💬 <b>Шаблон сообщения:</b>\n<i>{html.escape(tpl)}</i>"
    )


@router.callback_query(F.data == "menu:searches")
async def cb_list_searches(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    searches = await db.list_searches()
    if not searches:
        text = (
            "🔍 <b>Список поисков пуст</b>\n\n"
            "Нажмите «➕ Добавить поиск», чтобы задать поисковый запрос или ссылку с Avito."
        )
    else:
        text = (
            f"🔍 <b>Ваши поиски ({len(searches)} шт.)</b>\n\n"
            "Выберите поиск для управления, тестового запуска или настройки шаблона:"
        )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=searches_list_kb(searches),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("search:view:"))
async def cb_view_search(callback: CallbackQuery, db: Database) -> None:
    search_id = int(callback.data.split(":")[2])
    task = await db.get_search(search_id)
    if not task:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    settings = await db.get_bot_settings()
    await callback.message.edit_text(
        _format_search_card(task, settings.default_template),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=search_detail_kb(task),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("search:toggle:"))
async def cb_toggle_search(callback: CallbackQuery, db: Database) -> None:
    search_id = int(callback.data.split(":")[2])
    task = await db.toggle_search_active(search_id)
    if not task:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    settings = await db.get_bot_settings()
    await callback.message.edit_text(
        _format_search_card(task, settings.default_template),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=search_detail_kb(task),
    )
    await callback.answer("Статус поиска обновлён")


@router.callback_query(F.data.startswith("search:toggle_ar:"))
async def cb_toggle_search_ar(callback: CallbackQuery, db: Database) -> None:
    search_id = int(callback.data.split(":")[2])
    task = await db.toggle_search_autoreply(search_id)
    if not task:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    settings = await db.get_bot_settings()
    await callback.message.edit_text(
        _format_search_card(task, settings.default_template),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=search_detail_kb(task),
    )
    await callback.answer("Автоотклик для поиска переключён")


@router.callback_query(F.data.startswith("search:scan:"))
async def cb_scan_search_now(
    callback: CallbackQuery,
    db: Database,
    monitor: AvitoMonitorService,
) -> None:
    search_id = int(callback.data.split(":")[2])
    task = await db.get_search(search_id)
    if not task:
        await callback.answer("Поиск не найден", show_alert=True)
        return
    await callback.answer("Проверяю выдачу Avito...")
    res = await monitor.process_single_search(task)
    updated = await db.get_search(search_id)
    settings = await db.get_bot_settings()
    await callback.message.edit_text(
        _format_search_card(updated or task, settings.default_template)
        + f"\n\n⚡️ <i>Результат проверки: новых — {res['new_items']}, откликов — {res['replied']}</i>",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=search_detail_kb(updated or task),
    )


@router.callback_query(F.data.startswith("search:delete:"))
async def cb_delete_search(callback: CallbackQuery, db: Database) -> None:
    search_id = int(callback.data.split(":")[2])
    await db.delete_search(search_id)
    searches = await db.list_searches()
    await callback.message.edit_text(
        "🗑 <b>Поиск удалён.</b>",
        parse_mode="HTML",
        reply_markup=searches_list_kb(searches),
    )
    await callback.answer("Удалено")


# -------------------- РЕДАКТИРОВАНИЕ ШАБЛОНА ПОИСКА --------------------


@router.callback_query(F.data.startswith("search:edit_tpl:"))
async def cb_edit_search_tpl(callback: CallbackQuery, state: FSMContext) -> None:
    search_id = int(callback.data.split(":")[2])
    await state.set_state(EditSearchTemplateStates.waiting_template)
    await state.update_data(search_id=search_id)
    await callback.message.edit_text(
        "✏️ <b>Введите индивидуальный шаблон автоотклика для этого поиска</b>\n\n"
        "Доступные переменные:\n"
        "• <code>{title}</code> — название объявления\n"
        "• <code>{price}</code> — цена\n"
        "• <code>{city}</code> — город\n"
        "• <code>{seller}</code> — имя продавца\n\n"
        "Отправьте <code>-</code> (минус), чтобы использовать общий шаблон по умолчанию.",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb(f"search:view:{search_id}"),
    )
    await callback.answer()


@router.message(EditSearchTemplateStates.waiting_template)
async def msg_save_search_tpl(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    search_id = int(data["search_id"])
    raw = (message.text or "").strip()
    tpl = "" if raw == "-" else raw
    await db.update_search_template(search_id, tpl)
    await state.clear()

    task = await db.get_search(search_id)
    settings = await db.get_bot_settings()
    if task:
        await message.answer(
            "✅ Шаблон обновлён!\n\n" + _format_search_card(task, settings.default_template),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=search_detail_kb(task),
        )


# -------------------- МАСТЕР СОЗДАНИЯ ПОИСКА --------------------


@router.callback_query(F.data == "search:add")
async def cb_add_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddSearchStates.waiting_name)
    await callback.message.edit_text(
        "➕ <b>Создание нового поиска (Шаг 1/6)</b>\n\n"
        "Введите короткое название для этой задачи мониторинга\n"
        "<i>Например: iPhone 15 Pro Москва или Ноутбуки RTX</i>",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:searches"),
    )
    await callback.answer()


@router.message(AddSearchStates.waiting_name)
async def msg_search_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Введите название длиной минимум 2 символа.")
        return
    await state.update_data(name=name)
    await state.set_state(AddSearchStates.waiting_url_or_query)
    await message.answer(
        "➕ <b>Шаг 2/6 — Ссылка поиска или ключевой запрос</b>\n\n"
        "Вы можете отправить:\n"
        "1️⃣ <b>Готовую ссылку поиска с Avito</b> (с нужными фильтрами, категорией и городом)\n"
        "2️⃣ Или просто <b>текстовый запрос</b> (например: <code>MacBook Air M2</code>)",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:searches"),
    )


@router.message(AddSearchStates.waiting_url_or_query)
async def msg_search_url_or_query(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Отправьте ссылку на Avito или поисковый запрос.")
        return

    if raw.startswith("http://") or raw.startswith("https://"):
        try:
            normalized_url = build_search_url(raw)
        except ValueError as exc:
            await message.answer(f"❌ {exc}\nПопробуйте ещё раз:")
            return
        await state.update_data(is_direct_url=True, search_url=normalized_url, query="", region="custom")
        await state.set_state(AddSearchStates.waiting_price_range)
        await message.answer(
            "➕ <b>Шаг 3/6 — Фильтр по цене (необязательно)</b>\n\n"
            "Укажите диапазон цены в рублях через дефис, например: <code>15000-45000</code>\n"
            "Или отправьте <code>-</code>, чтобы не ограничивать цену.",
            parse_mode="HTML",
            reply_markup=cancel_fsm_kb("menu:searches"),
        )
    else:
        await state.update_data(is_direct_url=False, query=raw)
        await state.set_state(AddSearchStates.waiting_region)
        await message.answer(
            "➕ <b>Шаг 3/6 — Город или регион</b>\n\n"
            "Введите город (например: <code>Москва</code>, <code>Краснодар</code>, <code>Туапсе</code>) "
            "или отправьте <code>-</code> для поиска по всей России.",
            parse_mode="HTML",
            reply_markup=cancel_fsm_kb("menu:searches"),
        )


@router.message(AddSearchStates.waiting_region)
async def msg_search_region(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    region = "rossiya" if raw in ("", "-") else raw
    await state.update_data(region=region)
    await state.set_state(AddSearchStates.waiting_price_range)
    await message.answer(
        "➕ <b>Шаг 4/6 — Диапазон цены (в рублях)</b>\n\n"
        "Введите <code>мин-макс</code> (например: <code>10000-50000</code>), "
        "только максимум <code>0-30000</code>, или <code>-</code> без ограничений:",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:searches"),
    )


@router.message(AddSearchStates.waiting_price_range)
async def msg_search_price(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    min_price = None
    max_price = None

    if raw != "-":
        cleaned = raw.replace(" ", "")
        if "-" in cleaned:
            parts = cleaned.split("-", 1)
            if parts[0].isdigit() and int(parts[0]) > 0:
                min_price = int(parts[0])
            if parts[1].isdigit() and int(parts[1]) > 0:
                max_price = int(parts[1])
        elif cleaned.isdigit():
            max_price = int(cleaned)
        else:
            await message.answer("Неверный формат цены. Введите например <code>10000-50000</code> или <code>-</code>.", parse_mode="HTML")
            return

    await state.update_data(min_price=min_price, max_price=max_price)
    await state.set_state(AddSearchStates.waiting_keywords)
    await message.answer(
        "➕ <b>Шаг 5/6 — Стоп-слова (минус-слова)</b>\n\n"
        "Перечислите через запятую слова, при наличии которых объявление нужно пропускать\n"
        "<i>Например: разбор, запчасти, разбитый, копия</i>\n"
        "Или отправьте <code>-</code>, чтобы пропустить.",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:searches"),
    )


@router.message(AddSearchStates.waiting_keywords)
async def msg_search_keywords(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    exclude_words = "" if raw == "-" else raw
    await state.update_data(exclude_words=exclude_words)
    await state.set_state(AddSearchStates.waiting_template)
    await message.answer(
        "➕ <b>Шаг 6/6 — Шаблон автоотклика для этого поиска</b>\n\n"
        "Введите текст сообщения продавцу (можно использовать <code>{title}</code>, <code>{price}</code>, <code>{city}</code>)\n"
        "Или отправьте <code>-</code>, чтобы использовать общий шаблон из настроек.",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:searches"),
    )


@router.message(AddSearchStates.waiting_template)
async def msg_search_finish(
    message: Message,
    state: FSMContext,
    db: Database,
    monitor: AvitoMonitorService,
) -> None:
    raw = (message.text or "").strip()
    reply_template = "" if raw == "-" else raw
    data = await state.get_data()

    if data.get("is_direct_url"):
        final_url = build_search_url(
            data["search_url"],
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
        )
    else:
        final_url = build_search_url(
            data["query"],
            region=data.get("region", "rossiya"),
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
        )

    task = await db.create_search(
        name=data["name"],
        search_url=final_url,
        query=data.get("query", ""),
        region=data.get("region", "rossiya"),
        min_price=data.get("min_price"),
        max_price=data.get("max_price"),
        exclude_words=data.get("exclude_words", ""),
        reply_template=reply_template,
        auto_reply=True,
    )
    await state.clear()
    settings = await db.get_bot_settings()

    await message.answer(
        "✅ <b>Поиск успешно создан!</b>\n\n" + _format_search_card(task, settings.default_template),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=search_detail_kb(task),
    )
    # Сразу выполняем первичную индексацию текущей выдачи в фоне
    await monitor.process_single_search(task)

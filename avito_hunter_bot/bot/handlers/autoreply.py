from __future__ import annotations

import html
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from avito.messenger import AvitoMessengerService
from bot.keyboards import autoreply_menu_kb, cancel_fsm_kb, main_menu_kb
from bot.states import AutoReplySettingsStates
from database.db import Database
from database.models import AvitoItem
from services.scheduler import build_item_keyboard

router = Router()


def _format_autoreply_screen(settings) -> str:
    state_label = "🟢 ВКЛЮЧЁН" if settings.auto_reply_enabled else "🔴 ВЫКЛЮЧЕН"
    return (
        "💬 <b>Настройки автоотклика и безопасности</b>\n\n"
        f"• <b>Глобальный статус:</b> {state_label}\n"
        f"• <b>Лимит в час:</b> {settings.hourly_limit} сообщ.\n"
        f"• <b>Лимит в сутки:</b> {settings.daily_limit} сообщ.\n"
        f"• <b>Задержка перед откликом:</b> {settings.reply_delay_min}–{settings.reply_delay_max} сек.\n"
        f"• <b>Антиспам по одному продавцу:</b> {settings.dedup_seller_days} дн.\n"
        f"• <b>Интервал проверки поисков:</b> ~{settings.scan_interval_sec} сек.\n\n"
        f"📝 <b>Общий шаблон сообщения:</b>\n<i>{html.escape(settings.default_template)}</i>"
    )


@router.callback_query(F.data == "menu:autoreply")
async def cb_autoreply_menu(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    settings = await db.get_bot_settings()
    await callback.message.edit_text(
        _format_autoreply_screen(settings),
        parse_mode="HTML",
        reply_markup=autoreply_menu_kb(settings.auto_reply_enabled),
    )
    await callback.answer()


@router.callback_query(F.data == "autoreply:toggle_global")
async def cb_toggle_global_autoreply(callback: CallbackQuery, db: Database) -> None:
    settings = await db.get_bot_settings()
    new_val = not settings.auto_reply_enabled
    await db.set_setting("auto_reply_enabled", "1" if new_val else "0")
    updated = await db.get_bot_settings()

    # Обновляем текущий экран в зависимости от того, откуда нажали (из главного меню или настроек)
    current_text = callback.message.text or ""
    if "Настройки автоотклика" in current_text:
        await callback.message.edit_text(
            _format_autoreply_screen(updated),
            parse_mode="HTML",
            reply_markup=autoreply_menu_kb(updated.auto_reply_enabled),
        )
    else:
        from bot.handlers.start import build_dashboard_text
        await callback.message.edit_text(
            await build_dashboard_text(db),
            parse_mode="HTML",
            reply_markup=main_menu_kb(updated.auto_reply_enabled),
        )
    await callback.answer("Автоотклик включён" if new_val else "Автоотклик выключен")


@router.callback_query(F.data == "autoreply:edit_tpl")
async def cb_edit_default_template(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoReplySettingsStates.waiting_default_template)
    await callback.message.edit_text(
        "✏️ <b>Введите новый общий шаблон автоотклика</b>\n\n"
        "Доступные теги подстановки:\n"
        "• <code>{title}</code> — название объявления\n"
        "• <code>{price}</code> — цена\n"
        "• <code>{city}</code> — город\n"
        "• <code>{seller}</code> — имя продавца\n"
        "• <code>{url}</code> — ссылка на объявление",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:autoreply"),
    )
    await callback.answer()


@router.message(AutoReplySettingsStates.waiting_default_template)
async def msg_save_default_template(message: Message, state: FSMContext, db: Database) -> None:
    tpl = (message.text or "").strip()
    if len(tpl) < 3:
        await message.answer("Текст шаблона слишком короткий.")
        return
    await db.set_setting("default_template", tpl)
    await state.clear()
    settings = await db.get_bot_settings()
    await message.answer(
        "✅ Общий шаблон сохранён!\n\n" + _format_autoreply_screen(settings),
        parse_mode="HTML",
        reply_markup=autoreply_menu_kb(settings.auto_reply_enabled),
    )


@router.callback_query(F.data == "autoreply:edit_limits")
async def cb_edit_limits(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoReplySettingsStates.waiting_limits)
    await callback.message.edit_text(
        "🛡 <b>Настройка лимитов безопасности и задержек</b>\n\n"
        "Отправьте 5 чисел через пробел:\n"
        "<code>час_лимит сут_лимит мин_задержка макс_задержка дней_антиспам_продавца</code>\n\n"
        "<i>Пример:</i> <code>10 50 8 25 7</code>\n"
        "(макс. 10/час, 50/сутки, задержка 8–25 сек, не писать повторно продавцу 7 дней)",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:autoreply"),
    )
    await callback.answer()


@router.message(AutoReplySettingsStates.waiting_limits)
async def msg_save_limits(message: Message, state: FSMContext, db: Database) -> None:
    parts = (message.text or "").strip().split()
    if len(parts) != 5 or not all(p.isdigit() for p in parts):
        await message.answer(
            "❌ Введите ровно 5 целых чисел через пробел, например: <code>10 50 8 25 7</code>",
            parse_mode="HTML",
        )
        return

    hourly, daily, d_min, d_max, dedup_days = map(int, parts)
    if hourly < 1 or daily < hourly or d_min < 1 or d_max < d_min:
        await message.answer("❌ Проверьте логику чисел (суточный лимит >= часового, макс. задержка >= мин.).")
        return

    await db.set_setting("hourly_limit", hourly)
    await db.set_setting("daily_limit", daily)
    await db.set_setting("reply_delay_min", d_min)
    await db.set_setting("reply_delay_max", d_max)
    await db.set_setting("dedup_seller_days", dedup_days)
    await state.clear()

    settings = await db.get_bot_settings()
    await message.answer(
        "✅ Лимиты обновлены!\n\n" + _format_autoreply_screen(settings),
        parse_mode="HTML",
        reply_markup=autoreply_menu_kb(settings.auto_reply_enabled),
    )


@router.callback_query(F.data == "autoreply:edit_interval")
async def cb_edit_interval(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoReplySettingsStates.waiting_scan_interval)
    await callback.message.edit_text(
        "⏱ <b>Интервал сканирования поисков (в секундах)</b>\n\n"
        "Введите число от <code>20</code> до <code>3600</code> (рекомендуется 40–90 сек):",
        parse_mode="HTML",
        reply_markup=cancel_fsm_kb("menu:autoreply"),
    )
    await callback.answer()


@router.message(AutoReplySettingsStates.waiting_scan_interval)
async def msg_save_interval(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (20 <= int(raw) <= 3600):
        await message.answer("Введите целое число от 20 до 3600.")
        return
    await db.set_setting("scan_interval_sec", int(raw))
    await state.clear()
    settings = await db.get_bot_settings()
    await message.answer(
        "✅ Интервал обновлён!\n\n" + _format_autoreply_screen(settings),
        parse_mode="HTML",
        reply_markup=autoreply_menu_kb(settings.auto_reply_enabled),
    )


# -------------------- РУЧНОЙ ОТКЛИК ПО КНОПКЕ В УВЕДОМЛЕНИИ --------------------


@router.callback_query(F.data.startswith("manual_reply:"))
async def cb_manual_reply(
    callback: CallbackQuery,
    db: Database,
    messenger: AvitoMessengerService,
) -> None:
    _, search_id_str, item_id = callback.data.split(":", 2)
    search_id = int(search_id_str)

    if await db.has_replied_to_item(item_id):
        await callback.answer("Отклик по этому объявлению уже отправлен!", show_alert=True)
        return

    cursor = await db.conn.execute("SELECT * FROM seen_items WHERE item_id = ?", (item_id,))
    row = await cursor.fetchone()
    if not row:
        await callback.answer("Объявление не найдено в базе.", show_alert=True)
        return

    item = AvitoItem(
        item_id=row["item_id"],
        title=row["title"],
        price=row["price"],
        price_text=f"{row['price']} ₽" if row["price"] else "Цена не указана",
        url=row["url"],
        city=row["city"] or "",
        seller_id=row["seller_id"] or "",
    )

    task = await db.get_search(search_id)
    settings = await db.get_bot_settings()
    template = (task.reply_template.strip() if task else "") or settings.default_template

    await callback.answer("Отправляю сообщение продавцу...")
    res = await messenger.send_reply(item, template)

    if res.success:
        await db.log_reply(
            item_id=item.item_id,
            seller_id=item.seller_id,
            channel_id=res.channel_id,
            message_text=res.message_text,
            status="sent",
        )
        old_text = callback.message.html_text or ""
        await callback.message.edit_text(
            old_text + f"\n\n✅ <b>Отклик отправлен вручную:</b>\n<i>«{html.escape(res.message_text)}»</i>",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_item_keyboard(item, search_id, already_replied=True),
        )
    else:
        await db.log_reply(
            item_id=item.item_id,
            seller_id=item.seller_id,
            channel_id=res.channel_id,
            message_text=res.message_text,
            status="error",
            error_message=res.error,
        )
        await callback.message.answer(
            f"❌ <b>Не удалось отправить отклик:</b> {html.escape(res.error)}",
            parse_mode="HTML",
        )

from __future__ import annotations

import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import back_to_main_kb, main_menu_kb
from database.db import Database
from services.cookie_helper import cookies_from_json
from services.proxy_helper import mask_proxy
from services.scheduler import AvitoMonitorService

router = Router()


async def build_dashboard_text(db: Database) -> str:
    settings = await db.get_bot_settings()
    stats = await db.get_stats()
    cookies = cookies_from_json(settings.avito_cookies_json)

    acc_status = (
        f"✅ Подключён ({len(cookies)} cookies)"
        if cookies
        else "❌ Не подключён"
    )
    ar_status = "🟢 Включён" if settings.auto_reply_enabled else "🔴 Выключен"

    return (
        "🤖 <b>Avito Hunter & Auto-Reply Bot</b>\n\n"
        f"👤 <b>Аккаунт Avito:</b> {acc_status}\n"
        f"🌐 <b>Прокси:</b> <code>{html.escape(mask_proxy(settings.proxy_url))}</code>\n"
        f"💬 <b>Автоотклик:</b> {ar_status}\n"
        f"🔍 <b>Активных поисков:</b> {stats['active_searches']} из {stats['total_searches']}\n"
        f"⏱ <b>Интервал проверки:</b> ~{settings.scan_interval_sec} сек.\n\n"
        f"📨 <b>Откликов сегодня:</b> {stats['sent_last_24h']} / {settings.daily_limit} "
        f"(за час: {stats['sent_last_hour']} / {settings.hourly_limit})"
    )


@router.message(Command("start", "menu"))
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    settings = await db.get_bot_settings()
    text = await build_dashboard_text(db)
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_kb(settings.auto_reply_enabled),
    )


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    settings = await db.get_bot_settings()
    text = await build_dashboard_text(db)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_kb(settings.auto_reply_enabled),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:stats")
async def cb_stats(callback: CallbackQuery, db: Database) -> None:
    settings = await db.get_bot_settings()
    stats = await db.get_stats()

    text = (
        "📊 <b>Подробная статистика</b>\n\n"
        f"🔍 <b>Всего поисков:</b> {stats['total_searches']} (активных: {stats['active_searches']})\n"
        f"📦 <b>Найдено объявлений в базе:</b> {stats['total_seen_items']}\n"
        f"✉️ <b>Отправлено откликов всего:</b> {stats['total_sent_replies']}\n"
        f"🕒 <b>Откликов за 1 час:</b> {stats['sent_last_hour']} / {settings.hourly_limit}\n"
        f"📅 <b>Откликов за 24 часа:</b> {stats['sent_last_24h']} / {settings.daily_limit}\n\n"
        f"⚠️ <b>Последняя ошибка отклика:</b>\n<code>{html.escape(stats['last_error'])}</code>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_to_main_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:run_now")
async def cb_run_now(
    callback: CallbackQuery,
    db: Database,
    monitor: AvitoMonitorService,
) -> None:
    await callback.answer("Запускаю внеочередную проверку поисков...")
    res = await monitor.run_all_active_searches()
    settings = await db.get_bot_settings()

    text = (
        "⚡️ <b>Внеочередная проверка завершена</b>\n\n"
        f"🔍 Проверено поисков: <b>{res['searches']}</b>\n"
        f"🆕 Найдено новых объявлений: <b>{res['new_items']}</b>\n"
        f"✉️ Отправлено автооткликов: <b>{res['replied']}</b>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu_kb(settings.auto_reply_enabled),
    )

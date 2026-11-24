from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import main_menu_kb
from config import settings
from database import models

router = Router()


async def _build_dashboard_text() -> str:
    searches = await models.get_searches()
    active_count = sum(1 for s in searches if s["is_active"])
    account = await models.get_account()
    auto_reply = await models.get_setting("auto_reply_enabled", "1") == "1"
    hourly_limit = await models.get_setting("hourly_limit", "15")
    sent_hour = await models.get_sent_count_last_hour()
    bl_count = await models.get_blacklist_count()

    if settings.AVITO_ACCESS_TOKEN and settings.AVITO_USER_ID:
        acc_status = "🟢 Официальный API подключен"
    elif account and account["is_valid"]:
        acc_status = "🟢 Привязан (Cookies активны)"
    elif account:
        acc_status = "🔴 Сессия устарела (обновите cookies)"
    else:
        acc_status = "⚪ Не привязан"

    ar_status = "🟢 Включен" if auto_reply else "⏸ На паузе"

    return (
        "<b>🦅 Avito Sniper Bot — Панель управления</b>\n\n"
        f"• <b>Аккаунт Avito:</b> {acc_status}\n"
        f"• <b>Автоотклик первым:</b> {ar_status}\n"
        f"• <b>Активных поисков:</b> {active_count} из {len(searches)}\n"
        f"• <b>Отправлено за час:</b> {sent_hour} / {hourly_limit} сообщ.\n"
        f"• <b>Продавцов в ЧС:</b> {bl_count}\n\n"
        "Выберите раздел для настройки:"
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    text = await _build_dashboard_text()
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = await _build_dashboard_text()
    await callback.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="HTML")
    await callback.answer()

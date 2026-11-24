from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from bot.keyboards import main_menu_kb
from config import settings
from database import db

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await db.get_user_settings(message.from_user.id)
    await message.answer(
        "🦅 <b>Avito Sniper Bot — Buyer Edition</b>\n\n"
        "Бот настроен под быстрый и безопасный выкуп лотов с любого устройства:\n"
        "• <b>1-клик отклик:</b> в каждом уведомлении уже готово уникальное сообщение — нажмите на текст, "
        "чтобы скопировать, и нажмите <b>«🚀 Открыть в Avito»</b>.\n"
        "• <b>Гибкие фильтры:</b> снайпер-цена, плюс-слова, стоп-слова, фильтр частников и процент выгоды от рынка.\n"
        "• <b>Мульти-устройства:</b> все настройки и избранное привязаны к вашему профилю.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("grant"))
async def cmd_grant(message: Message) -> None:
    if settings.admin_ids_list and message.from_user.id not in settings.admin_ids_list:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/grant 123456789</code> (ID нового устройства/покупателя)", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.grant_user_access(target_id)
    await message.answer(f"✅ Доступ к боту выдан пользователю <code>{target_id}</code>.", parse_mode="HTML")


@router.message(Command("revoke"))
async def cmd_revoke(message: Message) -> None:
    if settings.admin_ids_list and message.from_user.id not in settings.admin_ids_list:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: <code>/revoke 123456789</code>", parse_mode="HTML")
        return
    target_id = int(parts[1])
    await db.revoke_user_access(target_id)
    await message.answer(f"🚫 Доступ отозван у пользователя <code>{target_id}</code>.", parse_mode="HTML")
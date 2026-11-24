from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from bot.keyboards import main_menu_kb
from config import settings

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "🦅 <b>Avito Sniper Bot</b> готов к работе!\n\n"
        "• Нажмите <b>«➕ Добавить поиск»</b>, чтобы отслеживать свежие объявления.\n"
        "• Нажмите <b>«👤 Мой Avito»</b>, чтобы привязать аккаунт (с ПК или с телефона) для автоотклика.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message) -> None:
    proxy_state = "🟢 Подключён" if settings.PROXY_URL else "⚪️ Не задан"
    await message.answer(
        "⚙️ <b>Системные параметры</b>\n\n"
        f"• Интервал проверки: <b>{settings.CHECK_INTERVAL_SEC} сек.</b>\n"
        f"• Мобильный прокси: {proxy_state}\n"
        f"• База данных: <code>{settings.DB_PATH}</code>",
        parse_mode="HTML",
    )
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import cancel_kb, main_menu_kb
from bot.states import ActionStates
from database import db
from services.avito_messenger import send_first_message

router = Router()


@router.callback_query(F.data.startswith("reply_"))
async def ask_custom_reply(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = callback.data.split("_", 1)[1]
    await state.set_state(ActionStates.waiting_custom_message)
    await state.update_data(reply_item_id=item_id)
    await callback.message.answer(
        f"💬 Введите сообщение для продавца объявления <code>#{item_id}</code>:",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ActionStates.waiting_custom_message)
async def send_custom_reply(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("reply_item_id")
    if not item_id or not message.text:
        await state.clear()
        return

    user_settings = await db.get_user_settings(message.from_user.id)
    cookies_raw = (user_settings or {}).get("avito_cookies")
    ok, info = await send_first_message(item_id=item_id, text=message.text.strip(), cookies_json=cookies_raw)
    await state.clear()

    prefix = "✅" if ok else "❌"
    await message.answer(f"{prefix} {info}", reply_markup=main_menu_kb())


@router.callback_query(F.data.startswith("ban_"))
async def ban_seller(callback: CallbackQuery) -> None:
    seller_id = callback.data.split("_", 1)[1]
    await db.add_to_blacklist(callback.from_user.id, seller_id)
    await callback.answer("🚫 Продавец добавлен в чёрный список", show_alert=True)
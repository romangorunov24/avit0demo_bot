from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from bot.keyboards import cancel_kb
from bot.states import ActionStates
from database import models
from services.avito_messenger import send_first_message

router = Router()


@router.callback_query(F.data.startswith("act:bl:"))
async def cb_blacklist_seller(callback: CallbackQuery) -> None:
    seller_id = callback.data.split(":")[2]
    if not seller_id or seller_id == "unknown":
        await callback.answer("ID продавца не определен для этого объявления", show_alert=True)
        return
    await models.add_to_blacklist(seller_id)
    await callback.answer("🚫 Продавец добавлен в черный список", show_alert=True)


@router.callback_query(F.data.startswith("act:msg:"))
async def cb_custom_msg_start(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = callback.data.split(":")[2]
    await state.update_data(target_item_id=item_id)
    await state.set_state(ActionStates.waiting_custom_message)
    await callback.message.answer(
        f"💬 Введите текст дополнительного сообщения для объявления <code>{item_id}</code>:",
        reply_markup=cancel_kb("menu:main"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ActionStates.waiting_custom_message)
async def msg_custom_msg_send(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Сообщение не может быть пустым.")
        return
    data = await state.get_data()
    item_id = data["target_item_id"]
    await state.clear()

    ok, info = await send_first_message(item_id=item_id, text=text, seller_id="manual")
    if ok:
        await message.answer(f"✅ Сообщение отправлено продавцу!\n<i>«{text}»</i>", parse_mode="HTML")
    else:
        await message.answer(f"⚠️ Не удалось отправить: {info}")

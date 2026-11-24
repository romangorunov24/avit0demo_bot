from aiogram import F, Router
from aiogram.types import CallbackQuery
from bot.keyboards import item_card_kb
from database import db
from services.spintax import render_spintax
from services.worker import build_item_caption

router = Router()


@router.callback_query(F.data.startswith("reroll:"))
async def reroll_card_message(callback: CallbackQuery) -> None:
    _, mode, item_id = callback.data.split(":", 2)
    item = await db.get_recent_item(item_id)
    if not item:
        await callback.answer("Данные карточки устарели", show_alert=True)
        return

    u = await db.get_user_settings(callback.from_user.id)
    tpl_map = {
        "main": u.get("default_template") or "{Здравствуйте|Добрый день}! {Актуально|Ещё продаёте}? Готов забрать сегодня.",
        "bargain": u.get("bargain_template") or "{Здравствуйте|Добрый день}! За {price_bargain} ₽ отдадите, если подъеду сегодня?",
        "delivery": u.get("delivery_template") or "{Здравствуйте|Добрый день}! Авито Доставкой сможете отправить?",
    }
    ready_msg = render_spintax(tpl_map.get(mode, tpl_map["main"]), title=item.get("title", ""), price=item.get("price"))
    caption = build_item_caption(item, item.get("search_name") or "Поиск", ready_msg)
    kb = item_card_kb(item["url"], item_id)

    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.edit_text(caption, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        pass

    await callback.answer("✅ Текст обновлён — нажмите на него, чтобы скопировать!")


@router.callback_query(F.data.startswith("fav_add:"))
async def add_to_favorites_cb(callback: CallbackQuery) -> None:
    item_id = callback.data.split(":", 1)[1]
    item = await db.get_recent_item(item_id)
    if not item:
        await callback.answer("Лот не найден в кэше", show_alert=True)
        return
    await db.add_favorite(
        user_id=callback.from_user.id,
        item_id=item_id,
        title=item.get("title") or f"Объявление #{item_id}",
        price=item.get("price"),
        url=item.get("url") or f"https://www.avito.ru/items/{item_id}",
    )
    await callback.answer("⭐ Добавлено в Избранное!")


@router.callback_query(F.data.startswith("ban:"))
async def ban_seller_cb(callback: CallbackQuery) -> None:
    seller_id = callback.data.split(":", 1)[1]
    await db.add_to_blacklist(callback.from_user.id, seller_id)
    await callback.answer("🚫 Продавец добавлен в чёрный список", show_alert=True)
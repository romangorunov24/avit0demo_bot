from aiogram import F, Router
from aiogram.types import CallbackQuery
from bot.keyboards import item_card_kb
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies
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
    has_acc = bool(normalize_cookies(u.get("avito_cookies") or ""))
    kb = item_card_kb(item["url"], item_id, can_send_now=has_acc)

    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.edit_text(caption, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        pass

    await callback.answer("✅ Текст обновлён!")


@router.callback_query(F.data.startswith("send_now:"))
async def send_message_now_cb(callback: CallbackQuery) -> None:
    item_id = callback.data.split(":", 1)[1]
    item = await db.get_recent_item(item_id)
    if not item:
        await callback.answer("Данные карточки устарели", show_alert=True)
        return

    u = await db.get_user_settings(callback.from_user.id)
    cookies_raw = u.get("avito_cookies")
    if not normalize_cookies(cookies_raw or ""):
        await callback.answer("Сначала подключите аккаунт Avito!", show_alert=True)
        return

    await callback.answer("⏳ Отправляю сообщение в Avito...")
    raw_tpl = u.get("default_template") or "{Здравствуйте|Добрый день}! {Актуально|Ещё продаёте}? Готов забрать сегодня."
    ready_msg = render_spintax(raw_tpl, title=item.get("title", ""), price=item.get("price"))

    messenger = AvitoMessenger()
    ok, info, security_alert = await messenger.send_message(
        item_id=item_id,
        item_url=item["url"],
        text=ready_msg,
        cookies_json=cookies_raw,
    )
    await db.log_sent_message(
        user_id=callback.from_user.id,
        item_id=item_id,
        seller_id=None,
        item_title=item.get("title") or "",
        message_text=ready_msg,
        status="sent" if ok else "failed",
    )
    if security_alert:
        await db.update_user_field(callback.from_user.id, "auto_reply_enabled", 0)

    if ok:
        await callback.message.answer(f"✅ Сообщение отправлено продавцу!\nТекст: <i>«{ready_msg}»</i>", parse_mode="HTML")
    else:
        await callback.message.answer(f"⚠️ Не удалось отправить: {info}")


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
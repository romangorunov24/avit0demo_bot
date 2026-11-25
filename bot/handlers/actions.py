import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from bot.keyboards import item_card_kb
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies
from services.spintax import render_spintax
from services.worker import (
    DEFAULT_TEMPLATE,
    IN_FLIGHT,
    PHOTO_CAPTION_LIMIT,
    build_item_caption,
    check_send_allowed,
    send_lock,
)

logger = logging.getLogger(__name__)
router = Router()


BARGAIN_DEFAULT = "{Здравствуйте|Добрый день}! За {price_bargain} ₽ отдадите, если подъеду сегодня?"
DELIVERY_DEFAULT = "{Здравствуйте|Добрый день}! Авито Доставкой сможете отправить?"


@router.callback_query(F.data.startswith("reroll:"))
async def reroll_card_message(callback: CallbackQuery) -> None:
    _, mode, item_id = callback.data.split(":", 2)
    user_id = callback.from_user.id
    item = await db.get_recent_item(item_id)
    if not item:
        await callback.answer("Данные карточки устарели", show_alert=True)
        return

    u = await db.get_user_settings(user_id)
    # Основной шаблон: у поиска может быть свой
    search = await db.get_search_owned(int(item["search_id"]), user_id) if item.get("search_id") else None
    tpl_map = {
        "main": (search or {}).get("message_template") or u.get("default_template") or DEFAULT_TEMPLATE,
        "bargain": u.get("bargain_template") or BARGAIN_DEFAULT,
        "delivery": u.get("delivery_template") or DELIVERY_DEFAULT,
    }
    ready_msg = render_spintax(tpl_map.get(mode, tpl_map["main"]), title=item.get("title", ""), price=item.get("price"))
    search_name = item.get("search_name") or "Поиск"
    is_photo = bool(callback.message.photo)
    caption = build_item_caption(item, search_name, ready_msg)
    if is_photo and len(caption) > PHOTO_CAPTION_LIMIT:
        caption = build_item_caption(item, search_name, ready_msg, desc_limit=60)
    has_acc = bool(normalize_cookies(u.get("avito_cookies") or ""))
    already_sent = await db.was_item_messaged(user_id, item_id)
    kb = item_card_kb(item["url"], item_id, item.get("seller_id"), can_send_now=(has_acc and not already_sent))

    try:
        if is_photo:
            await callback.message.edit_caption(caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.edit_text(caption, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        # «message is not modified» значит, на экране уже именно этот текст
        if "not modified" not in str(e).lower():
            logger.warning("Не удалось обновить текст карточки %s: %s", item_id, e)
            await callback.answer("Не удалось обновить текст, попробуйте ещё раз", show_alert=True)
            return

    # Запоминаем показанный текст: кнопка «Отправить» отправит именно его
    await db.save_draft(user_id, item_id, ready_msg)
    await callback.answer("✅ Текст обновлён!")


@router.callback_query(F.data.startswith("send_now:"))
async def send_message_now_cb(callback: CallbackQuery) -> None:
    item_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id
    item = await db.get_recent_item(item_id)
    if not item:
        await callback.answer("Данные карточки устарели", show_alert=True)
        return

    u = await db.get_user_settings(user_id)
    cookies_raw = u.get("avito_cookies")
    if not normalize_cookies(cookies_raw or ""):
        await callback.answer("Сначала подключите аккаунт Avito!", show_alert=True)
        return

    key = (user_id, item_id)
    if key in IN_FLIGHT:
        await callback.answer("Уже отправляю, подождите…")
        return

    seller_id = item.get("seller_id")
    IN_FLIGHT.add(key)
    try:
        await callback.answer("⏳ Отправляю сообщение в Avito...")
        # Очередь отправок пользователя общая с автооткликом: лимиты и «уже писали» проверяются под замком
        async with send_lock(user_id):
            u = await db.get_user_settings(user_id)
            cookies_raw = u.get("avito_cookies")
            reason = await check_send_allowed(user_id, item_id, seller_id, u)
            if reason:
                await callback.message.answer(f"⚠️ Не отправлено: {reason}")
                return

            # Отправляем ровно тот текст, который сейчас показан на карточке
            ready_msg = await db.get_draft(user_id, item_id)
            if not ready_msg:
                raw_tpl = u.get("default_template") or DEFAULT_TEMPLATE
                ready_msg = render_spintax(raw_tpl, title=item.get("title", ""), price=item.get("price"))

            outcome = await AvitoMessenger().send_message_ex(
                item_id=item_id,
                item_url=item["url"],
                text=ready_msg,
                cookies_json=cookies_raw,
            )
            await db.log_sent_message(
                user_id=user_id,
                item_id=item_id,
                seller_id=seller_id,
                item_title=item.get("title") or "",
                message_text=ready_msg,
                status="sent" if outcome.ok else "failed",
                info=outcome.info,
            )
            if outcome.security_alert:
                await db.update_user_field(user_id, "auto_reply_enabled", 0)
    finally:
        IN_FLIGHT.discard(key)

    if outcome.ok:
        await callback.message.answer("✅ Сообщение отправлено продавцу!")
        try:  # кнопку «Отправить» убираем, чтобы не нажимали повторно
            await callback.message.edit_reply_markup(
                reply_markup=item_card_kb(item["url"], item_id, seller_id, can_send_now=False)
            )
        except Exception:
            pass
    else:
        extra = "\n\nАвтоотклик выключен в целях безопасности." if outcome.security_alert else ""
        await callback.message.answer(f"⚠️ Не удалось отправить: {outcome.info}{extra}")


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

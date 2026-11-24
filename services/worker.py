import asyncio
import html
import logging
from aiogram import Bot
from bot.keyboards import item_notification_kb
from config import settings
from database import models
from services.avito_messenger import send_first_message
from services.avito_parser import AvitoItem, fetch_search_items, passes_filters
from services.spintax import render_spintax
from utils.helpers import calc_discount_percent

logger = logging.getLogger(__name__)


async def _notify_admins(
    bot: Bot,
    item: AvitoItem,
    search: dict,
    discount_pct: int | None,
    reply_status_line: str,
) -> None:
    safe_title = html.escape(item.title)
    safe_search = html.escape(search["name"])
    safe_desc = html.escape(item.description) if item.description else "Описание отсутствует"
    safe_loc = html.escape(item.location) if item.location else "Не указано"

    price_str = f"{item.price:,}".replace(",", " ") + " ₽" if item.price > 0 else "Цена не указана"
    discount_badge = (
        f"\n🔥 <b>Выгодно: на {discount_pct}% ниже средней цены!</b>"
        if discount_pct
        else ""
    )
    seller_type = "🏢 Магазин / Компания" if item.is_company else "👤 Частное лицо"

    caption = (
        f"🆕 <b>Новое объявление</b> [{safe_search}]\n\n"
        f"📌 <a href=\"{item.url}\"><b>{safe_title}</b></a>\n"
        f"💰 <b>Цена:</b> {price_str}{discount_badge}\n"
        f"📍 <b>Район:</b> {safe_loc}\n"
        f"🧾 <b>Продавец:</b> {seller_type}\n\n"
        f"📝 <i>{safe_desc[:250]}</i>\n\n"
        f"{reply_status_line}"
    )

    kb = item_notification_kb(item.url, item.item_id, item.seller_id)

    for admin_id in settings.admin_ids_list:
        sent_with_photo = False
        if item.image_url:
            try:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=item.image_url,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
                sent_with_photo = True
            except Exception as e:
                logger.warning("Не удалось отправить фото админу %s (%s), отправляю текстом.", admin_id, e)

        if not sent_with_photo:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=caption,
                    reply_markup=kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error("Не удалось отправить уведомление админу %s: %s", admin_id, e)


async def _process_search(bot: Bot, search: dict) -> None:
    sid = search["id"]
    items = await fetch_search_items(search)
    if not items:
        return

    already_seeded = await models.has_seen_items_for_search(sid)
    if not already_seeded:
        for it in items:
            await models.add_seen_item(it.item_id, sid, it.price)
        logger.info("Поиск '%s' инициализирован: сохранено %s стартовых объявлений.", search["name"], len(items))
        return

    avg_price = await models.get_average_price(sid, limit=50)
    auto_reply_global = await models.get_setting("auto_reply_enabled", "1") == "1"
    spintax_tpl = await models.get_setting("spintax_template")

    for it in reversed(items):
        if await models.is_item_seen(it.item_id):
            continue

        await models.add_seen_item(it.item_id, sid, it.price)

        if not await passes_filters(it, search):
            continue

        discount_pct = calc_discount_percent(it.price, avg_price)
        sniper_limit = search["sniper_price"] or 0

        should_reply = auto_reply_global and (
            sniper_limit == 0 or (it.price > 0 and it.price <= sniper_limit)
        )

        if should_reply:
            msg_text = render_spintax(spintax_tpl, title=it.title, price=it.price)
            ok, info = await send_first_message(
                item_id=it.item_id,
                text=msg_text,
                seller_id=it.seller_id,
            )
            if ok:
                reply_line = f"✅ <b>Написали первым:</b> <i>«{html.escape(msg_text)}»</i>"
            else:
                reply_line = f"⚠️ <b>Автоотклик не сработал:</b> {html.escape(info)}"
        else:
            if not auto_reply_global:
                reply_line = "⏸ <b>Автоотклик отключен</b> (можно написать вручную)"
            else:
                reply_line = f"🎯 <b>Цена выше порога «Снайпер» ({sniper_limit} ₽)</b> — уведомление без автоответа"

        await _notify_admins(bot, it, search, discount_pct, reply_line)


async def worker_loop(bot: Bot) -> None:
    logger.info("Фоновый мониторинг Авито запущен (интервал: %s сек.)", settings.CHECK_INTERVAL_SEC)
    while True:
        try:
            active_searches = await models.get_searches(only_active=True)
            for search in active_searches:
                await _process_search(bot, search)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("Фоновый воркер остановлен.")
            break
        except Exception as e:
            logger.exception("Непредвиденная ошибка в цикле воркера: %s", e)

        await asyncio.sleep(max(3, settings.CHECK_INTERVAL_SEC))

import asyncio
from datetime import datetime
import html
import logging
from aiogram import Bot
from bot.keyboards import item_card_kb
from config import settings
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies
from services.avito_parser import parse_avito_search
from services.spintax import render_spintax

logger = logging.getLogger(__name__)


def _has_stop_words(text: str, stop_words_raw: str | None) -> bool:
    if not stop_words_raw:
        return False
    low = text.lower()
    words = [w.strip().lower() for w in stop_words_raw.split(",") if w.strip()]
    return any(w in low for w in words)


def _has_plus_words(text: str, plus_words_raw: str | None) -> bool:
    if not plus_words_raw:
        return True
    low = text.lower()
    words = [w.strip().lower() for w in plus_words_raw.split(",") if w.strip()]
    if not words:
        return True
    return any(w in low for w in words)


def _is_quiet_time(quiet_hours: str | None) -> bool:
    if not quiet_hours or "-" not in quiet_hours:
        return False
    try:
        start_s, end_s = quiet_hours.strip().split("-", 1)
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        now = datetime.now()
        cur_m = now.hour * 60 + now.minute
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        if start_m <= end_m:
            return start_m <= cur_m < end_m
        return cur_m >= start_m or cur_m < end_m
    except Exception:
        return False


def build_item_caption(item: dict, search_name: str, ready_msg: str, is_sniper_hit: bool = False, auto_reply_note: str = "") -> str:
    price = item.get("price")
    price_str = f"{price:,} ₽".replace(",", " ") if price else "Не указана"

    sniper_banner = "🚨 <b>СРАБОТАЛА СНАЙПЕР-ЦЕНА!</b>\n" if is_sniper_hit else ""
    discount_line = ""
    if item.get("discount_pct") and item["discount_pct"] >= 10:
        discount_line = f"\n🔥 <b>Выгода:</b> на {item['discount_pct']}% ниже средней цены!"

    safe_search = html.escape(search_name)
    safe_title = html.escape(item.get("title") or "Без названия")
    safe_loc = html.escape(item.get("location") or "Не указано")
    safe_seller = html.escape(item.get("seller_type") or "Частное лицо")
    safe_desc = html.escape((item.get("description") or "Описание отсутствует")[:260])
    safe_msg = html.escape(ready_msg)

    return (
        f"🆕 <b>Новый лот</b> [{safe_search}]\n"
        f"{sniper_banner}\n"
        f"📌 <b>{safe_title}</b>\n"
        f"💰 Цена: <b>{price_str}</b>{discount_line}\n"
        f"📍 Район: {safe_loc}\n"
        f"👤 Продавец: {safe_seller}\n\n"
        f"📝 <i>{safe_desc}</i>\n\n"
        f"💬 <b>Сообщение (нажмите, чтобы скопировать):</b>\n"
        f"<code>{safe_msg}</code>"
        f"{auto_reply_note}"
    )


async def send_item_card(bot: Bot, user_id: int, item: dict, search: dict, user_settings: dict, silent: bool = False) -> None:
    item_id = str(item["id"])
    price = item.get("price")
    sniper_price = search.get("sniper_price")
    is_sniper_hit = bool(sniper_price and price and price <= sniper_price)

    raw_tpl = (
        search.get("message_template")
        or user_settings.get("default_template")
        or "{Здравствуйте|Добрый день}! {Объявление ещё актуально|Ещё продаёте}? Готов забрать сегодня."
    )
    ready_msg = render_spintax(raw_tpl, title=item.get("title", ""), price=price)

    auto_reply_note = ""
    cookies_raw = user_settings.get("avito_cookies")
    if user_settings.get("auto_reply_enabled") and normalize_cookies(cookies_raw or ""):
        messenger = AvitoMessenger()
        sent_ok, sent_info = await messenger.send_message(
            item_id=item_id,
            item_url=item["url"],
            text=ready_msg,
            cookies_json=cookies_raw,
        )
        if sent_ok:
            auto_reply_note = "\n\n✅ <b>Автоотклик отправлен в Avito!</b>"
        else:
            auto_reply_note = f"\n\nℹ️ <i>Автоотклик: {html.escape(sent_info)}</i>"

    await db.save_recent_item(item, search["name"])
    caption = build_item_caption(item, search["name"], ready_msg, is_sniper_hit=is_sniper_hit, auto_reply_note=auto_reply_note)
    kb = item_card_kb(item["url"], item_id, item.get("seller_id"))

    try:
        if item.get("image_url"):
            await bot.send_photo(
                chat_id=user_id,
                photo=item["image_url"],
                caption=caption,
                parse_mode="HTML",
                reply_markup=kb,
                disable_notification=silent,
            )
            return
    except Exception:
        pass

    await bot.send_message(
        chat_id=user_id,
        text=caption,
        parse_mode="HTML",
        reply_markup=kb,
        disable_web_page_preview=True,
        disable_notification=silent,
    )


async def process_single_search(bot: Bot, search: dict, force_preview: bool = False) -> int:
    search_id = search["id"]
    user_id = search["user_id"]
    title = search["name"]
    url = search["url"]

    user_settings = await db.get_user_settings(user_id)
    if user_settings.get("is_paused") and not force_preview:
        return 0

    items = await parse_avito_search(url, search_name=title)
    if not items:
        return 0

    if not await db.is_search_initialized(search_id) and not force_preview:
        for item in items:
            await db.mark_item_seen(search_id, str(item["id"]))
        await db.update_search_field(search_id, "is_initialized", 1)
        logger.info("Поиск '%s' инициализирован (%d стартовых лотов).", title, len(items))
        return 0

    silent = _is_quiet_time(user_settings.get("quiet_hours"))
    sent_count = 0

    for item in items:
        item_id = str(item["id"])
        if not force_preview and await db.is_item_seen(search_id, item_id):
            continue

        await db.mark_item_seen(search_id, item_id)

        seller_id = item.get("seller_id")
        if seller_id and await db.is_seller_blacklisted(user_id, str(seller_id)):
            continue

        effective_seller_filter = search.get("seller_filter") if search.get("seller_filter") not in (None, "all") else user_settings.get("seller_filter", "all")
        if effective_seller_filter in ("private", "company") and item.get("seller_code") != effective_seller_filter:
            continue

        price = item.get("price")
        min_price = search.get("min_price")
        max_price = search.get("max_price")
        if min_price and price and price < min_price:
            continue
        if max_price and price and price > max_price:
            continue

        if user_settings.get("only_profitable") and not force_preview:
            min_disc = user_settings.get("min_discount_pct") or 10
            if (item.get("discount_pct") or 0) < min_disc:
                continue

        full_text = f"{item.get('title', '')} {item.get('description', '')}"
        if not _has_plus_words(full_text, search.get("plus_words")):
            continue
        if _has_stop_words(full_text, search.get("stop_words")):
            continue

        await send_item_card(bot, user_id, item, search, user_settings, silent=silent)
        sent_count += 1

        if force_preview and sent_count >= 2:
            break

    return sent_count


async def worker_loop(bot: Bot) -> None:
    logger.info("Фоновый мониторинг запущен (интервал: %s сек.)", settings.CHECK_INTERVAL_SEC)
    while True:
        try:
            searches = await db.get_active_searches()
            for search in searches:
                await process_single_search(bot, search, force_preview=False)
                await asyncio.sleep(2)
        except Exception as e:
            logger.error("Ошибка в цикле worker_loop: %s", e)

        await asyncio.sleep(settings.CHECK_INTERVAL_SEC)
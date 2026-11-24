import asyncio
import html
import logging
import random
import time
from aiogram import Bot
from bot.keyboards import item_card_kb
from config import settings
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies
from services.avito_parser import parse_avito_search
from services.filters import has_plus_words, has_stop_words, is_quiet_time, memory_ok
from services.spintax import render_spintax

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = "{Здравствуйте|Добрый день}! {Объявление ещё актуально|Ещё продаёте}? Готов забрать сегодня."


def build_item_caption(
    item: dict,
    search_name: str,
    ready_msg: str,
    is_sniper_hit: bool = False,
    auto_reply_note: str = "",
) -> str:
    price = item.get("price")
    price_str = f"{price:,} ₽".replace(",", " ") if price else "Не указана"

    sniper_banner = "🚨 <b>СРАБОТАЛА СНАЙПЕР-ЦЕНА!</b>\n" if is_sniper_hit else ""
    discount_line = ""
    if item.get("discount_pct") and item["discount_pct"] >= 10:
        discount_line = f"\n🔥 <b>Выгода:</b> на {item['discount_pct']}% ниже медианы выдачи"

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
        f"💬 <b>Текст отклика (нажмите, чтобы скопировать):</b>\n"
        f"<code>{safe_msg}</code>"
        f"{auto_reply_note}"
    )


async def check_send_allowed(user_id: int, item_id: str, seller_id: str | None, us: dict) -> str | None:
    """Общие проверки перед любой отправкой (авто и ручной). Возвращает причину отказа или None."""
    if await db.was_item_messaged(user_id, item_id):
        return "по этому объявлению уже писали ранее"

    cooldown_h = int(us.get("seller_cooldown_hours") or 24)
    if await db.was_seller_messaged_recently(user_id, seller_id, cooldown_h):
        return f"этому продавцу уже писали за последние {cooldown_h} ч."

    max_h = int(us.get("max_replies_hour") or 8)
    max_d = int(us.get("max_replies_day") or 30)
    if await db.count_sent_messages(user_id, 1) >= max_h:
        return f"достигнут лимит {max_h} откликов в час"
    if await db.count_sent_messages(user_id, 24) >= max_d:
        return f"достигнут дневной лимит {max_d} откликов"
    return None


async def _try_auto_reply(user_id: int, item: dict, ready_msg: str, user_settings: dict) -> tuple[bool, str]:
    item_id = str(item["id"])
    seller_id = item.get("seller_id")
    cookies_raw = user_settings.get("avito_cookies")

    if not normalize_cookies(cookies_raw or ""):
        return False, "\n\n⚪️ <i>Автоотклик пропущен: аккаунт Avito не привязан.</i>"

    reason = await check_send_allowed(user_id, item_id, seller_id, user_settings)
    if reason:
        return False, f"\n\n🛡 <i>Антиспам: {html.escape(reason)}.</i>"

    d_min = max(1, int(user_settings.get("auto_delay_min") or 4))
    d_max = max(d_min, int(user_settings.get("auto_delay_max") or 10))
    await asyncio.sleep(random.uniform(d_min, d_max))

    messenger = AvitoMessenger()
    sent_ok, info, security_alert = await messenger.send_message(
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
        status="sent" if sent_ok else "failed",
    )

    if security_alert:
        await db.update_user_field(user_id, "auto_reply_enabled", 0)
        return False, f"\n\n🚨 <b>{html.escape(info)} Автоотклик выключен в настройках!</b>"

    if sent_ok:
        return True, "\n\n✅ <b>Автоотклик отправлен продавцу в Avito!</b>"

    return False, f"\n\n⚠️ <i>Автоотклик не ушёл: {html.escape(info)}</i>"


async def send_item_card(
    bot: Bot,
    user_id: int,
    item: dict,
    search: dict,
    user_settings: dict,
    silent: bool = False,
    allow_auto_reply: bool = True,
) -> None:
    item_id = str(item["id"])
    price = item.get("price")
    sniper_price = search.get("sniper_price")
    is_sniper_hit = bool(sniper_price and price and price <= sniper_price)

    raw_tpl = search.get("message_template") or user_settings.get("default_template") or DEFAULT_TEMPLATE
    ready_msg = render_spintax(raw_tpl, title=item.get("title", ""), price=price)

    auto_reply_note = ""
    sent_auto = False
    should_auto = (
        allow_auto_reply
        and bool(user_settings.get("auto_reply_enabled"))
        and bool(search.get("auto_reply", 1))
    )
    if should_auto:
        sent_auto, auto_reply_note = await _try_auto_reply(user_id, item, ready_msg, user_settings)

    await db.save_recent_item(item, search["name"])
    caption = build_item_caption(
        item,
        search["name"],
        ready_msg,
        is_sniper_hit=is_sniper_hit,
        auto_reply_note=auto_reply_note,
    )
    has_acc = bool(normalize_cookies(user_settings.get("avito_cookies") or ""))
    kb = item_card_kb(item["url"], item_id, item.get("seller_id"), can_send_now=(has_acc and not sent_auto))

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


async def item_passes_filters(item: dict, search: dict, user_settings: dict, user_id: int, force_preview: bool) -> bool:
    seller_id = item.get("seller_id")
    if seller_id and await db.is_seller_blacklisted(user_id, str(seller_id)):
        return False

    effective_seller_filter = (
        search.get("seller_filter")
        if search.get("seller_filter") not in (None, "all")
        else user_settings.get("seller_filter", "all")
    )
    if effective_seller_filter in ("private", "company") and item.get("seller_code") != effective_seller_filter:
        return False

    price = item.get("price")
    min_price = search.get("min_price")
    max_price = search.get("max_price")
    if min_price and price and price < min_price:
        return False
    if max_price and price and price > max_price:
        return False

    if user_settings.get("only_profitable") and not force_preview:
        min_disc = user_settings.get("min_discount_pct") or 10
        if (item.get("discount_pct") or 0) < min_disc:
            return False

    full_text = f"{item.get('title', '')} {item.get('description', '')}"
    if not memory_ok(full_text, search.get("memory")):
        return False
    if not has_plus_words(full_text, search.get("plus_words")):
        return False
    if has_stop_words(full_text, search.get("stop_words")):
        return False
    return True


async def process_single_search(bot: Bot, search: dict, force_preview: bool = False) -> int:
    search_id = search["id"]
    user_id = search["user_id"]
    title = search["name"]
    url = search["url"]

    user_settings = await db.get_user_settings(user_id)
    if user_settings.get("is_paused") and not force_preview:
        return 0

    items = await parse_avito_search(url, search_name=title, ignore_backoff=force_preview)
    if not items:
        return 0

    if not await db.is_search_initialized(search_id) and not force_preview:
        for item in items:
            await db.mark_item_seen(search_id, str(item["id"]))
        await db.update_search_field(search_id, "is_initialized", 1)
        logger.info("Поиск '%s' инициализирован (%d стартовых лотов).", title, len(items))
        return 0

    silent = is_quiet_time(user_settings.get("quiet_hours"))
    sent_count = 0

    for item in items:
        item_id = str(item["id"])
        if not force_preview and await db.is_item_seen(search_id, item_id):
            continue

        if not await item_passes_filters(item, search, user_settings, user_id, force_preview):
            if not force_preview:
                await db.mark_item_seen(search_id, item_id)
            continue

        try:
            await send_item_card(
                bot,
                user_id,
                item,
                search,
                user_settings,
                silent=silent,
                allow_auto_reply=(not force_preview),
            )
        except Exception as e:
            # Лот НЕ помечаем просмотренным: попробуем снова в следующем цикле.
            # Повторное сообщение продавцу исключено проверкой was_item_messaged.
            logger.error("Не удалось доставить карточку '%s' пользователю %s: %s", item_id, user_id, e)
            continue

        # Тестовая проверка ничего не помечает, чтобы не «съедать» лоты у реального мониторинга
        if not force_preview:
            await db.mark_item_seen(search_id, item_id)
        sent_count += 1

        if force_preview and sent_count >= 2:
            break

    return sent_count


async def worker_loop(bot: Bot) -> None:
    logger.info("Фоновый мониторинг запущен (базовый интервал: %s сек.)", settings.CHECK_INTERVAL_SEC)
    last_prune = 0.0
    while True:
        try:
            searches = await db.get_active_searches()
        except Exception as e:
            logger.error("Не удалось получить список поисков: %s", e)
            searches = []

        for search in searches:
            # Ошибка в одном поиске не должна останавливать остальные
            try:
                await process_single_search(bot, search, force_preview=False)
            except Exception as e:
                logger.error("Ошибка в поиске %s: %s", search.get("id"), e)
            await asyncio.sleep(random.uniform(2.5, 5.0))

        if time.time() - last_prune > 86400:
            try:
                await db.prune_old_data()
                last_prune = time.time()
            except Exception as e:
                logger.error("Очистка старых данных не удалась: %s", e)

        jitter = random.uniform(4.0, 16.0)
        await asyncio.sleep(settings.CHECK_INTERVAL_SEC + jitter)

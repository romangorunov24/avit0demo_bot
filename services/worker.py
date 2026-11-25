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

MAX_SEND_ATTEMPTS = 3            # попыток отправки одного отклика при безопасных сбоях (сеть, 5xx до отправки текста)
RATE_LIMIT_PAUSE_SEC = 30 * 60   # пауза автоотклика после ответа Авито 429
PHOTO_CAPTION_LIMIT = 1024       # лимит Telegram на подпись к фото
_AUTO_PAUSE_UNTIL: dict[int, float] = {}
MAX_DELIVERY_FAILS = 3           # столько раз пробуем доставить карточку, потом лот пропускаем (иначе вечный повтор)
_DELIVERY_FAILS: dict[tuple[int, str], int] = {}
_SEND_LOCKS: dict[int, asyncio.Lock] = {}
IN_FLIGHT: set[tuple[int, str]] = set()  # отправки, идущие прямо сейчас (общий для автоотклика и кнопки)


def send_lock(user_id: int) -> asyncio.Lock:
    """Отправки одного пользователя идут строго по очереди: проверка лимитов и сама отправка не гоняются друг с другом."""
    return _SEND_LOCKS.setdefault(user_id, asyncio.Lock())


async def user_is_active(user_id: int) -> bool:
    """Администратор или пользователь с выданным доступом. У отозванных поиски не обрабатываются."""
    return user_id in settings.admin_ids_list or await db.is_user_allowed(user_id)


def build_item_caption(
    item: dict,
    search_name: str,
    ready_msg: str,
    is_sniper_hit: bool = False,
    auto_reply_note: str = "",
    desc_limit: int = 260,
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
    safe_desc = html.escape((item.get("description") or "Описание отсутствует")[:desc_limit])
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

    # Сообщение по этому лоту уже ушло (например, карточку в Telegram не удалось доставить с первого раза)
    if await db.was_item_messaged(user_id, item_id):
        return True, "\n\n✅ <i>Автоотклик по этому объявлению уже был отправлен ранее.</i>"

    pause_left = _AUTO_PAUSE_UNTIL.get(user_id, 0.0) - time.time()
    if pause_left > 0:
        return False, f"\n\n⏸ <i>Автоотклик на паузе после лимита Авито ещё ~{int(pause_left // 60) + 1} мин.</i>"

    reason = await check_send_allowed(user_id, item_id, seller_id, user_settings)
    if reason:
        return False, f"\n\n🛡 <i>Антиспам: {html.escape(reason)}.</i>"

    d_min = max(1, int(user_settings.get("auto_delay_min") or 4))
    d_max = max(d_min, int(user_settings.get("auto_delay_max") or 10))
    await asyncio.sleep(random.uniform(d_min, d_max))

    messenger = AvitoMessenger()
    outcome = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        outcome = await messenger.send_message_ex(
            item_id=item_id,
            item_url=item["url"],
            text=ready_msg,
            cookies_json=cookies_raw,
        )
        if outcome.ok or not outcome.retryable or attempt == MAX_SEND_ATTEMPTS:
            break
        logger.info("Автоотклик по %s: попытка %d не удалась (%s), повторяю", item_id, attempt, outcome.info)
        await asyncio.sleep(random.uniform(5.0, 10.0))

    await db.log_sent_message(
        user_id=user_id,
        item_id=item_id,
        seller_id=seller_id,
        item_title=item.get("title") or "",
        message_text=ready_msg,
        status="sent" if outcome.ok else "failed",
        info=outcome.info,
    )

    if outcome.rate_limited:
        _AUTO_PAUSE_UNTIL[user_id] = time.time() + RATE_LIMIT_PAUSE_SEC
        logger.warning("Авито ответил 429: автоотклик пользователя %s на паузе %d мин.", user_id, RATE_LIMIT_PAUSE_SEC // 60)

    if outcome.security_alert:
        await db.update_user_field(user_id, "auto_reply_enabled", 0)
        user_settings["auto_reply_enabled"] = 0  # настройки общие для всех лотов прохода: остальные лоты тоже не пишем
        return False, f"\n\n🚨 <b>{html.escape(outcome.info)} Автоотклик выключен в настройках!</b>"

    if outcome.ok:
        return True, "\n\n✅ <b>Автоотклик отправлен продавцу в Avito!</b>"

    return False, f"\n\n⚠️ <i>Автоотклик не ушёл: {html.escape(outcome.info)}</i>"


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
        async with send_lock(user_id):
            sent_auto, auto_reply_note = await _try_auto_reply(user_id, item, ready_msg, user_settings)

    await db.save_recent_item(item, search["name"], search.get("id"))
    await db.save_draft(user_id, item_id, ready_msg)

    def make_caption(desc_limit: int) -> str:
        return build_item_caption(
            item,
            search["name"],
            ready_msg,
            is_sniper_hit=is_sniper_hit,
            auto_reply_note=auto_reply_note,
            desc_limit=desc_limit,
        )

    caption = make_caption(260)
    has_acc = bool(normalize_cookies(user_settings.get("avito_cookies") or ""))
    kb = item_card_kb(item["url"], item_id, item.get("seller_id"), can_send_now=(has_acc and not sent_auto))

    if item.get("image_url"):
        # У подписи к фото лимит 1024 символа: сокращаем описание, а если не помогло, шлём текстом без фото
        photo_caption = caption if len(caption) <= PHOTO_CAPTION_LIMIT else make_caption(60)
        if len(photo_caption) <= PHOTO_CAPTION_LIMIT:
            try:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=item["image_url"],
                    caption=photo_caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                    disable_notification=silent,
                )
                return
            except Exception as e:
                logger.info("Фото лота %s не отправилось (%s), шлю карточку текстом", item_id, str(e)[:100])

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

    if not force_preview and not await user_is_active(user_id):
        return 0  # доступ отозван: ни мониторинга, ни автоотклика с cookies этого пользователя

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
            # Лот пока НЕ помечаем просмотренным: попробуем снова в следующем цикле.
            # Повторное сообщение продавцу исключено проверкой was_item_messaged.
            key = (search_id, item_id)
            _DELIVERY_FAILS[key] = _DELIVERY_FAILS.get(key, 0) + 1
            logger.error("Не удалось доставить карточку '%s' пользователю %s (%d/%d): %s", item_id, user_id, _DELIVERY_FAILS[key], MAX_DELIVERY_FAILS, e)
            if _DELIVERY_FAILS[key] >= MAX_DELIVERY_FAILS and not force_preview:
                # Постоянная причина (бот заблокирован, неверная разметка): не повторяем бесконечно
                await db.mark_item_seen(search_id, item_id)
                _DELIVERY_FAILS.pop(key, None)
            continue
        _DELIVERY_FAILS.pop((search_id, item_id), None)

        # Тестовая проверка ничего не помечает, чтобы не «съедать» лоты у реального мониторинга
        if not force_preview:
            await db.mark_item_seen(search_id, item_id)
        sent_count += 1

        if force_preview and sent_count >= 2:
            break

    return sent_count


async def worker_loop(bot: Bot) -> None:
    interval = max(30, int(settings.CHECK_INTERVAL_SEC))
    logger.info("Фоновый мониторинг запущен (базовый интервал: %s сек.)", interval)
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
        await asyncio.sleep(interval + jitter)

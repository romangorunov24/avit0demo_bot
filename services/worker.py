import asyncio
import logging
from aiogram import Bot
from bot.keyboards import item_card_kb
from config import settings
from database import db
from services.avito_messenger import AvitoMessenger, normalize_cookies
from services.avito_parser import parse_avito_search
from services.spintax import render_spintax

logger = logging.getLogger(__name__)


async def worker_loop(bot: Bot) -> None:
    logger.info("Фоновый мониторинг Авито запущен (интервал: %s сек.)", settings.CHECK_INTERVAL_SEC)
    messenger = AvitoMessenger()

    while True:
        try:
            searches = await db.get_active_searches()
            for search in searches:
                search_id = search["id"]
                user_id = search["user_id"]
                title = search["name"]
                url = search["url"]

                user_settings = await db.get_user_settings(user_id)
                cookies_raw = (user_settings or {}).get("avito_cookies")
                has_account = bool(normalize_cookies(cookies_raw or ""))

                items = await parse_avito_search(url, cookies_json=cookies_raw)
                if not items:
                    await asyncio.sleep(2)
                    continue

                is_initialized = await db.is_search_initialized(search_id)
                if not is_initialized:
                    for item in items:
                        await db.mark_item_seen(search_id, str(item["id"]))
                    logger.info("Поиск '%s' инициализирован: сохранено %d стартовых объявлений.", title, len(items))
                    await asyncio.sleep(2)
                    continue

                for item in items:
                    item_id = str(item["id"])
                    if await db.is_item_seen(search_id, item_id):
                        continue

                    await db.mark_item_seen(search_id, item_id)

                    seller_id = item.get("seller_id")
                    if seller_id and await db.is_seller_blacklisted(user_id, str(seller_id)):
                        continue

                    price = item.get("price")
                    min_price = search.get("min_price")
                    max_price = search.get("max_price")
                    if min_price and price and price < min_price:
                        continue
                    if max_price and price and price > max_price:
                        continue

                    # Автоотклик запускается ТОЛЬКО если у пользователя привязан аккаунт и включён автоотклик
                    auto_reply_status = ""
                    auto_reply_enabled = bool(search.get("auto_reply", True))

                    if has_account and auto_reply_enabled:
                        raw_tpl = (
                            search.get("message_template")
                            or (user_settings or {}).get("default_template")
                            or "Здравствуйте! Объявление ещё актуально?"
                        )
                        msg_text = render_spintax(raw_tpl)
                        sent_ok, sent_info = await messenger.send_message(
                            item_id=item_id,
                            item_url=item["url"],
                            text=msg_text,
                            cookies_json=cookies_raw,
                        )
                        if sent_ok:
                            auto_reply_status = f"\n✅ <b>Автоотклик отправлен:</b> <i>«{msg_text}»</i>"
                        else:
                            auto_reply_status = f"\nℹ️ <b>Автоотклик:</b> {sent_info}"

                    price_str = f"{price:,} ₽".replace(",", " ") if price else "Не указана"
                    discount_line = ""
                    if item.get("discount_pct") and item["discount_pct"] >= 10:
                        discount_line = f"\n🔥 <b>Выгодно:</b> на {item['discount_pct']}% ниже средней цены!"

                    caption = (
                        f"🆕 <b>Новое объявление</b> [{title}]\n\n"
                        f"📌 <b>{item['title']}</b>\n"
                        f"💰 Цена: <b>{price_str}</b>{discount_line}\n"
                        f"📍 Район: {item.get('location') or 'Не указано'}\n"
                        f"👤 Продавец: {item.get('seller_type') or 'Частное лицо'}\n\n"
                        f"📝 <i>{(item.get('description') or 'Описание отсутствует')[:300]}</i>"
                        f"{auto_reply_status}"
                    )

                    kb = item_card_kb(item["url"], item_id, seller_id, has_account)

                    try:
                        if item.get("image_url"):
                            await bot.send_photo(
                                chat_id=user_id,
                                photo=item["image_url"],
                                caption=caption,
                                parse_mode="HTML",
                                reply_markup=kb,
                            )
                        else:
                            await bot.send_message(
                                chat_id=user_id,
                                text=caption,
                                parse_mode="HTML",
                                reply_markup=kb,
                                disable_web_page_preview=True,
                            )
                    except Exception as send_err:
                        logger.warning("Ошибка отправки фото, шлю текстом: %s", send_err)
                        await bot.send_message(
                            chat_id=user_id,
                            text=caption,
                            parse_mode="HTML",
                            reply_markup=kb,
                            disable_web_page_preview=True,
                        )

                await asyncio.sleep(2)
        except Exception as e:
            logger.error("Ошибка в цикле worker_loop: %s", e)

        await asyncio.sleep(settings.CHECK_INTERVAL_SEC)

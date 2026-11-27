from __future__ import annotations

import asyncio
import html
import logging
import random
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from avito.client import AvitoHttpClient
from avito.exceptions import AvitoAuthError, AvitoRateLimitError
from avito.messenger import AvitoMessengerService
from avito.parser import filter_items, parse_search_page
from database.db import Database
from database.models import AvitoItem, SearchTask

logger = logging.getLogger(__name__)


def build_item_keyboard(item: AvitoItem, search_id: int, already_replied: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🔗 Открыть на Avito", url=item.url)],
    ]
    if not already_replied:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✉️ Отправить отклик вручную",
                    callback_data=f"manual_reply:{search_id}:{item.item_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_item_caption(item: AvitoItem, task: SearchTask, reply_status: str) -> str:
    promo_badge = " ⬆️ <i>(Продвинуто)</i>" if item.is_promoted else ""
    city_line = f"📍 <b>Город:</b> {html.escape(item.city)}\n" if item.city else ""
    seller_line = f"👤 <b>Продавец:</b> {html.escape(item.seller_name)}\n" if item.seller_name else ""
    desc_line = ""
    if item.description:
        short_desc = item.description[:220] + ("..." if len(item.description) > 220 else "")
        desc_line = f"📝 {html.escape(short_desc)}\n\n"

    return (
        f"🆕 <b>Новое объявление</b> [{html.escape(task.name)}]{promo_badge}\n\n"
        f"📦 <b>{html.escape(item.title)}</b>\n"
        f"💰 <b>Цена:</b> {html.escape(item.price_text)}\n"
        f"{city_line}"
        f"{seller_line}\n"
        f"{desc_line}"
        f"🤖 <b>Автоотклик:</b> {reply_status}"
    )


class AvitoMonitorService:
    """
    Фоновый планировщик мониторинга поисков Avito и очереди автооткликов:
    - Интервалы с джиттером (случайным разбросом)
    - Безопасные паузы перед отправкой сообщений
    - Контроль часового/суточного лимитов и антиспам по продавцам
    """

    def __init__(
        self,
        bot: Bot,
        db: Database,
        client: AvitoHttpClient,
        messenger: AvitoMessengerService,
        admin_ids: list[int],
    ):
        self.bot = bot
        self.db = db
        self.client = client
        self.messenger = messenger
        self.admin_ids = admin_ids
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._run_lock = asyncio.Lock()
        self._cooldown_until: float = 0.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._loop(), name="avito_monitor_loop")
            logger.info("Фоновый мониторинг Avito запущен.")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Фоновый мониторинг Avito остановлен.")

    async def _notify_admins(
        self,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        for admin_id in self.admin_ids:
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
            except Exception as exc:
                logger.warning("Не удалось отправить уведомление админу %s: %s", admin_id, exc)

    async def _loop(self) -> None:
        # Небольшая стартовая пауза после запуска бота
        await asyncio.sleep(3)
        while not self._stop_event.is_set():
            settings = await self.db.get_bot_settings()
            now_mono = asyncio.get_running_loop().time()

            if now_mono < self._cooldown_until:
                wait_left = int(self._cooldown_until - now_mono)
                logger.info("Пауза после лимита Avito: осталось %s сек.", wait_left)
                await asyncio.sleep(min(wait_left, 15))
                continue

            try:
                await self.run_all_active_searches()
            except Exception as exc:
                logger.exception("Неожиданная ошибка в цикле мониторинга: %s", exc)

            jitter = random.uniform(0.85, 1.25)
            sleep_sec = max(15.0, settings.scan_interval_sec * jitter)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_sec)
            except asyncio.TimeoutError:
                pass

    async def run_all_active_searches(self) -> dict[str, int]:
        async with self._run_lock:
            tasks = await self.db.list_searches(only_active=True)
            total_new = 0
            total_replied = 0

            for idx, task in enumerate(tasks):
                if self._stop_event.is_set():
                    break
                res = await self.process_single_search(task)
                total_new += res["new_items"]
                total_replied += res["replied"]

                # Пауза между разными поисками, чтобы не создавать всплеск запросов
                if idx < len(tasks) - 1:
                    await asyncio.sleep(random.uniform(3.0, 6.5))

            return {"searches": len(tasks), "new_items": total_new, "replied": total_replied}

    async def process_single_search(self, task: SearchTask) -> dict[str, int]:
        settings = await self.db.get_bot_settings()
        stats = {"new_items": 0, "replied": 0}

        try:
            resp = await self.client.request("GET", task.search_url, timeout=25)
            items = parse_search_page(resp.text)
            filtered = filter_items(items, task)
            await self.db.mark_search_checked(task.id, initialized=True)

            # Первый запуск поиска: запоминаем текущую выдачу, чтобы не спамить старыми объявлениями
            if not task.initialized:
                for item in filtered:
                    await self.db.save_seen_item(item, search_id=task.id, notified=True, replied=False)
                await self._notify_admins(
                    f"✅ <b>Поиск «{html.escape(task.name)}» инициализирован</b>\n"
                    f"В базу добавлено текущих объявлений: <b>{len(filtered)}</b>.\n"
                    f"Теперь бот будет мгновенно присылать все новые объявления."
                )
                return stats

            # Ищем только действительно новые объявления (идём снизу вверх, от более ранних к самым свежим)
            new_items: list[AvitoItem] = []
            for item in reversed(filtered):
                if not await self.db.is_item_seen(item.item_id):
                    new_items.append(item)

            for item in new_items:
                stats["new_items"] += 1
                should_reply, skip_reason = await self._evaluate_autoreply(item, task, settings)

                if should_reply:
                    delay = random.uniform(
                        max(2, settings.reply_delay_min),
                        max(settings.reply_delay_min + 1, settings.reply_delay_max),
                    )
                    logger.info(
                        "Найдено новое объявление %s. Пауза %.1f сек перед автооткликом...",
                        item.item_id,
                        delay,
                    )
                    await asyncio.sleep(delay)

                    template = task.reply_template.strip() or settings.default_template
                    send_res = await self.messenger.send_reply(item, template)

                    if send_res.success:
                        stats["replied"] += 1
                        await self.db.save_seen_item(item, search_id=task.id, notified=True, replied=True)
                        await self.db.log_reply(
                            item_id=item.item_id,
                            seller_id=item.seller_id,
                            channel_id=send_res.channel_id,
                            message_text=send_res.message_text,
                            status="sent",
                        )
                        caption = format_item_caption(
                            item,
                            task,
                            f"✅ <b>Отправлен</b>\n💬 <i>«{html.escape(send_res.message_text)}»</i>",
                        )
                        await self._notify_admins(
                            caption,
                            reply_markup=build_item_keyboard(item, task.id, already_replied=True),
                        )
                    else:
                        await self.db.save_seen_item(item, search_id=task.id, notified=True, replied=False)
                        await self.db.log_reply(
                            item_id=item.item_id,
                            seller_id=item.seller_id,
                            channel_id=send_res.channel_id,
                            message_text=send_res.message_text,
                            status="error",
                            error_message=send_res.error,
                        )
                        caption = format_item_caption(
                            item,
                            task,
                            f"❌ <b>Ошибка отправки:</b> {html.escape(send_res.error)}",
                        )
                        await self._notify_admins(
                            caption,
                            reply_markup=build_item_keyboard(item, task.id, already_replied=False),
                        )
                else:
                    await self.db.save_seen_item(item, search_id=task.id, notified=True, replied=False)
                    caption = format_item_caption(item, task, f"⏸ {html.escape(skip_reason)}")
                    await self._notify_admins(
                        caption,
                        reply_markup=build_item_keyboard(item, task.id, already_replied=False),
                    )

        except AvitoRateLimitError as exc:
            logger.warning("RateLimit при проверке поиска '%s': %s", task.name, exc)
            self._cooldown_until = asyncio.get_running_loop().time() + 180
            await self._notify_admins(
                f"⚠️ <b>Антибот / Лимит запросов Avito (HTTP {exc.status_code})</b>\n"
                f"Поиск: <b>{html.escape(task.name)}</b>\n"
                f"Мониторинг поставлен на паузу на 3 минуты. При повторении смените прокси."
            )
        except AvitoAuthError as exc:
            logger.error("Ошибка авторизации Avito: %s", exc)
            await self._notify_admins(
                f"🔐 <b>Проблема с сессией Avito</b>\n{html.escape(str(exc))}\n"
                f"Перейдите в раздел «👤 Аккаунт Avito» и обновите cookies."
            )
        except Exception as exc:
            logger.error("Ошибка проверки поиска '%s': %s", task.name, exc)

        return stats

    async def _evaluate_autoreply(self, item: AvitoItem, task: SearchTask, settings) -> tuple[bool, str]:
        if not settings.auto_reply_enabled:
            return False, "Выключен глобально"
        if not task.auto_reply:
            return False, "Выключен для этого поиска"
        if not self.client.cookies:
            return False, "Не подключён аккаунт Avito (нет cookies)"
        if await self.db.has_replied_to_item(item.item_id):
            return False, "Отклик по этому объявлению уже отправлялся"
        if await self.db.has_replied_to_seller_recently(item.seller_id, settings.dedup_seller_days):
            return False, f"Продавцу уже писали за последние {settings.dedup_seller_days} дн."

        sent_1h = await self.db.count_sent_replies_since(1)
        if sent_1h >= settings.hourly_limit:
            return False, f"Достигнут часовой лимит ({settings.hourly_limit}/ч)"

        sent_24h = await self.db.count_sent_replies_since(24)
        if sent_24h >= settings.daily_limit:
            return False, f"Достигнут суточный лимит ({settings.daily_limit}/сут)"

        return True, "Готов к отправке"

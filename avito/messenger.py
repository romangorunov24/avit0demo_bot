from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from avito.client import AvitoHttpClient
from avito.exceptions import AvitoAuthError, AvitoMessengerError
from database.models import AvitoItem

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AccountProfile:
    is_authorized: bool
    user_id: str = ""
    name: str = ""
    details: str = ""


@dataclass(slots=True)
class SendReplyResult:
    success: bool
    channel_id: str = ""
    message_text: str = ""
    error: str = ""


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_reply_template(template: str, item: AvitoItem) -> str:
    """Безопасная подстановка переменных объявления в шаблон автоотклика."""
    mapping = _SafeFormatDict(
        title=item.title,
        price=item.price_text,
        city=item.city or "не указан",
        seller=item.seller_name or "Здравствуйте",
        url=item.url,
    )
    rendered = template.format_map(mapping).strip()
    return rendered


class AvitoMessengerService:
    """
    Сервис работы с аккаунтом Avito и отправки автооткликов (сообщений продавцам)
    через внутреннее Messenger API веб-версии Avito.
    """

    def __init__(self, client: AvitoHttpClient):
        self.client = client

    def _api_headers(self, referer: str = "https://www.avito.ru/profile/messenger") -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://www.avito.ru",
            "Referer": referer,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }

    async def check_account(self) -> AccountProfile:
        """Проверяет валидность подключённых cookies аккаунта Avito."""
        if not self.client.cookies:
            return AccountProfile(
                is_authorized=False,
                details="Cookies аккаунта не загружены.",
            )

        # Пробуем получить краткий профиль пользователя
        endpoints = [
            "https://www.avito.ru/web/1/profile/short",
            "https://www.avito.ru/web/1/messenger/channels?limit=1",
        ]
        for url in endpoints:
            try:
                resp = await self.client.request(
                    "GET",
                    url,
                    headers=self._api_headers("https://www.avito.ru/"),
                    timeout=20,
                    check_antibot=False,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json() if hasattr(resp, "json") else __import__("json").loads(resp.text)
                    except Exception:
                        data = {}

                    user_id = str(
                        data.get("id")
                        or data.get("userId")
                        or (data.get("result") or {}).get("userId")
                        or ""
                    ).strip()
                    name = str(
                        data.get("name")
                        or data.get("title")
                        or (data.get("result") or {}).get("name")
                        or "Аккаунт Avito"
                    ).strip()

                    if user_id or "channels" in str(data) or "result" in data:
                        return AccountProfile(
                            is_authorized=True,
                            user_id=user_id or "active",
                            name=name,
                            details="Сессия активна, мессенджер Avito доступен.",
                        )
                elif resp.status_code in (401, 403):
                    return AccountProfile(
                        is_authorized=False,
                        details=f"Сессия отклонена сервером (HTTP {resp.status_code}). Требуется обновить cookies.",
                    )
            except Exception as exc:
                logger.debug("Ошибка при проверке endpoint %s: %s", url, exc)

        # Резервная проверка по странице профиля
        try:
            prof_resp = await self.client.request(
                "GET",
                "https://www.avito.ru/profile",
                timeout=20,
                check_antibot=False,
            )
            if prof_resp.status_code == 200 and "/profile/login" not in prof_resp.url:
                m_id = re.search(r'"userId"\s*:\s*(\d+)', prof_resp.text)
                uid = m_id.group(1) if m_id else "verified"
                return AccountProfile(
                    is_authorized=True,
                    user_id=uid,
                    name="Аккаунт Avito",
                    details="Авторизация подтверждена через страницу профиля.",
                )
        except Exception as exc:
            return AccountProfile(is_authorized=False, details=f"Ошибка сети при проверке профиля: {exc}")

        return AccountProfile(
            is_authorized=False,
            details="Не удалось подтвердить авторизацию. Проверьте актуальность cookies.",
        )

    async def _create_or_get_channel(self, item: AvitoItem) -> str:
        """Создаёт или получает существующий чат (channelId) по объявлению."""
        item_id_int = int(item.item_id) if item.item_id.isdigit() else item.item_id
        headers = self._api_headers(referer=item.url)

        # Вариант 1: /web/1/messenger/createItemChannel
        payload_v1 = {
            "itemId": item_id_int,
            "context": "item",
        }
        resp1 = await self.client.request(
            "POST",
            "https://www.avito.ru/web/1/messenger/createItemChannel",
            headers=headers,
            json_data=payload_v1,
            timeout=20,
        )
        if resp1.status_code == 200:
            data = __import__("json").loads(resp1.text)
            channel_id = (
                data.get("channelId")
                or (data.get("channel") or {}).get("id")
                or (data.get("result") or {}).get("channelId")
                or ((data.get("result") or {}).get("channel") or {}).get("id")
            )
            if channel_id:
                return str(channel_id)

        # Вариант 2: /web/1/messenger/item/{item_id}/channel
        resp2 = await self.client.request(
            "POST",
            f"https://www.avito.ru/web/1/messenger/item/{item.item_id}/channel",
            headers=headers,
            json_data={},
            timeout=20,
        )
        if resp2.status_code == 200:
            data2 = __import__("json").loads(resp2.text)
            channel_id = (
                data2.get("channelId")
                or (data2.get("channel") or {}).get("id")
                or (data2.get("result") or {}).get("channelId")
            )
            if channel_id:
                return str(channel_id)

        if resp1.status_code in (401, 403) or resp2.status_code in (401, 403):
            raise AvitoAuthError("Требуется повторная авторизация аккаунта Avito (cookies устарели).")

        raise AvitoMessengerError(
            f"Не удалось открыть чат по объявлению {item.item_id} "
            f"(возможно, продавец отключил сообщения). Коды: {resp1.status_code}/{resp2.status_code}"
        )

    async def send_reply(self, item: AvitoItem, template_or_text: str) -> SendReplyResult:
        """Отправляет сообщение продавцу по указанному объявлению."""
        message_text = render_reply_template(template_or_text, item)
        if not message_text:
            return SendReplyResult(success=False, error="Пустой текст сообщения.")

        try:
            channel_id = await self._create_or_get_channel(item)
            idempotency_key = str(uuid.uuid4())
            headers = self._api_headers(referer=f"https://www.avito.ru/profile/messenger/channel/{channel_id}")

            payload = {
                "channelId": channel_id,
                "body": {"text": message_text},
                "idempotencyKey": idempotency_key,
            }

            resp = await self.client.request(
                "POST",
                "https://www.avito.ru/web/1/messenger/sendTextMessage",
                headers=headers,
                json_data=payload,
                timeout=20,
            )

            if resp.status_code == 200:
                return SendReplyResult(
                    success=True,
                    channel_id=channel_id,
                    message_text=message_text,
                )

            return SendReplyResult(
                success=False,
                channel_id=channel_id,
                message_text=message_text,
                error=f"Ошибка отправки сообщения: HTTP {resp.status_code} ({resp.text[:160]})",
            )
        except Exception as exc:
            return SendReplyResult(
                success=False,
                message_text=message_text,
                error=str(exc),
            )

import asyncio
import json
import logging
import random
import re
from typing import Any
from curl_cffi.requests import AsyncSession
from services.proxy_helper import get_proxy_candidates

logger = logging.getLogger(__name__)


def normalize_cookies(raw_cookies: str | list[dict[str, Any]] | dict[str, Any]) -> dict[str, str]:
    important_keys = {"u", "v", "sessid", "srv_id", "ft", "auth", "f", "sx", "buyer_location_id"}
    result: dict[str, str] = {}

    if isinstance(raw_cookies, str):
        text = raw_cookies.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                parsed = json.loads(text)
                return normalize_cookies(parsed)
            except json.JSONDecodeError:
                pass

        for block in re.findall(r"\{[^{}]+\}", text):
            name_m = re.search(r'"name"\s*:\s*"([^"]+)"', block)
            val_m = re.search(r'"value"\s*:\s*"([^"]*)"', block)
            if name_m and val_m:
                k, v = name_m.group(1).strip(), val_m.group(1).strip()
                if k in important_keys and v:
                    result[k] = v

        for part in text.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k in important_keys and v:
                    result[k] = v
        return result

    if isinstance(raw_cookies, list):
        for item in raw_cookies:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain", ""))
            name = str(item.get("name", "")).strip()
            value = str(item.get("value", "")).strip()
            if ("avito.ru" in domain or not domain) and name in important_keys and value:
                result[name] = value
        return result

    if isinstance(raw_cookies, dict):
        for k, v in raw_cookies.items():
            if k in important_keys and v:
                result[str(k)] = str(v).strip()
        return result

    return result


class AvitoMessenger:
    def _build_headers(self, item_url: str) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://www.avito.ru",
            "Referer": item_url or "https://www.avito.ru/",
            "X-Requested-With": "XMLHttpRequest",
            "X-Source": "web",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    async def check_session(self, cookies_json: str | None) -> tuple[bool, str]:
        cookies = normalize_cookies(cookies_json or "")
        if not cookies:
            return False, "Не найдены ключевые cookies Авито (u, v, sessid)."

        headers = self._build_headers("https://www.avito.ru/profile")
        last_err = ""

        for proxies in get_proxy_candidates():
            try:
                async with AsyncSession(impersonate="chrome124", proxies=proxies, timeout=20) as session:
                    resp = await session.get(
                        "https://www.avito.ru/web/1/profile/short",
                        cookies=cookies,
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        name = data.get("name") or data.get("user", {}).get("name") or "Профиль Avito"
                        return True, f"Аккаунт подключён и активен: {name}"
                    if resp.status_code == 429:
                        return False, "IP упёрся в лимит Авито (HTTP 429). Подождите или смените IP."
                    if resp.status_code == 403:
                        return False, "Блок смены IP или WAF (HTTP 403). Запускайте бота с того же IP, где входили в аккаунт."
                    if resp.status_code == 401:
                        return False, "Сессия устарела (HTTP 401). Войдите в Avito заново и обновите cookies."
                    return False, f"Avito вернул статус {resp.status_code}."
            except Exception as e:
                last_err = str(e)
                if "Proxy CONNECT aborted" in last_err:
                    continue
                break

        return False, f"Ошибка соединения: {last_err[:150]}"

    async def send_message(
        self,
        item_id: int | str,
        item_url: str,
        text: str,
        cookies_json: str | None = None,
    ) -> tuple[bool, str, bool]:
        """
        Возвращает (успех, описание_статуса, тревога_безопасности_401_403).
        """
        cookies = normalize_cookies(cookies_json or "")
        if not cookies:
            return False, "Аккаунт Avito не привязан", False

        try:
            numeric_item_id = int(str(item_id).strip())
        except ValueError:
            return False, f"Некорректный ID объявления: {item_id}", False

        headers = self._build_headers(item_url)
        last_err = ""

        for proxies in get_proxy_candidates():
            try:
                async with AsyncSession(impersonate="chrome124", proxies=proxies, timeout=25) as session:
                    # 1. Имитируем открытие карточки товара перед нажатием «Написать»
                    try:
                        await session.get(
                            item_url,
                            cookies=cookies,
                            headers={
                                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                "Referer": "https://www.avito.ru/",
                                "Sec-Fetch-Dest": "document",
                                "Sec-Fetch-Mode": "navigate",
                                "Sec-Fetch-Site": "same-origin",
                            },
                        )
                    except Exception:
                        pass

                    # Пауза 1.5–3 сек. как при чтении объявления человеком
                    await asyncio.sleep(random.uniform(1.5, 3.0))

                    endpoints = [
                        (
                            "https://www.avito.ru/web/1/messenger/createChannelByItemId",
                            {"itemId": numeric_item_id},
                            "channel",
                        ),
                        (
                            "https://www.avito.ru/web/2/messenger/createChannelByItemId",
                            {"itemId": numeric_item_id},
                            "channel",
                        ),
                        (
                            f"https://www.avito.ru/web/1/items/{numeric_item_id}/messenger/send",
                            {"message": {"text": text}, "type": "text"},
                            "direct",
                        ),
                    ]

                    channel_id: str | None = None
                    last_status: int | None = None

                    for url, payload, mode in endpoints:
                        resp = await session.post(url, json=payload, cookies=cookies, headers=headers)
                        last_status = resp.status_code

                        if resp.status_code in (401, 403):
                            return (
                                False,
                                f"Защита Avito ({resp.status_code}): автоотклик остановлен для сохранения аккаунта.",
                                True,
                            )
                        if resp.status_code == 429:
                            return False, "Лимит запросов (HTTP 429). Пауза перед следующей отправкой.", False

                        if resp.status_code == 400:
                            body = resp.text.lower()
                            if "closed" in body or "disabled" in body or "недоступ" in body:
                                return False, "Продавец отключил сообщения в этом объявлении.", False

                        if resp.status_code in (200, 201):
                            data = resp.json()
                            if mode == "direct":
                                return True, "Сообщение доставлено продавцу", False
                            channel_id = (
                                data.get("channel", {}).get("id")
                                or data.get("result", {}).get("channel", {}).get("id")
                                or data.get("id")
                                or data.get("channelId")
                            )
                            if channel_id:
                                break

                    if not channel_id:
                        if last_status == 404:
                            return False, "Объявление уже снято или чат закрыт (404).", False
                        return False, f"Не удалось создать чат (HTTP {last_status or 'ERR'}).", False

                    for send_url, send_payload in (
                        (
                            "https://www.avito.ru/web/1/messenger/sendTextMessage",
                            {"channelId": channel_id, "text": text, "randomId": f"sniper_{numeric_item_id}_{random.randint(100,999)}"},
                        ),
                        (
                            f"https://www.avito.ru/web/1/messenger/channels/{channel_id}/messages",
                            {"type": "text", "message": {"text": text}},
                        ),
                    ):
                        s_resp = await session.post(send_url, json=send_payload, cookies=cookies, headers=headers)
                        if s_resp.status_code in (200, 201):
                            return True, "Сообщение доставлено продавцу", False
                        if s_resp.status_code in (401, 403):
                            return False, f"Защита Avito ({s_resp.status_code}) при отправке.", True
                        last_status = s_resp.status_code

                    return False, f"Чат открыт, но текст не принят (HTTP {last_status or 'ERR'}).", False
            except Exception as e:
                last_err = str(e)
                if "Proxy CONNECT aborted" in last_err:
                    continue
                break

        return False, f"Ошибка сети при отправке: {last_err[:120]}", False
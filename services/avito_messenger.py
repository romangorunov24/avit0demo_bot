import json
import logging
import re
from typing import Any
from curl_cffi.requests import AsyncSession
from config import settings

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
    def __init__(self, proxy_url: str | None = None) -> None:
        self.proxy_url = proxy_url or settings.PROXY_URL

    def _build_headers(self, item_url: str, access_token: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://www.avito.ru",
            "Referer": item_url or "https://www.avito.ru/",
            "X-Requested-With": "XMLHttpRequest",
            "X-Source": "web",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    async def check_session(self, cookies_json: str | None, access_token: str | None = None) -> tuple[bool, str]:
        cookies = normalize_cookies(cookies_json or "")
        if not cookies and not access_token:
            return False, "Не найдены ключевые cookies Авито (u, v, sessid)."

        proxies = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None
        headers = self._build_headers("https://www.avito.ru/profile", access_token)

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
                    return True, f"Аккаунт подключён: {name}"
                if resp.status_code == 429:
                    return False, "IP прокси упёрся в лимит (HTTP 429). Смените IP."
                if resp.status_code == 403:
                    return False, "Блок WAF или смены IP (HTTP 403). Используйте единый прокси при входе."
                if resp.status_code == 401:
                    return False, "Сессия устарела (HTTP 401). Обновите cookies."
                return False, f"Avito вернул статус {resp.status_code}."
        except Exception as e:
            logger.warning("Ошибка проверки сессии Avito: %s", e)
            return False, f"Ошибка соединения через прокси: {e}"

    async def send_message(
        self,
        item_id: int | str,
        item_url: str,
        text: str,
        cookies_json: str | None = None,
        access_token: str | None = None,
    ) -> tuple[bool, str]:
        cookies = normalize_cookies(cookies_json or "")
        token = access_token or settings.AVITO_ACCESS_TOKEN

        if not cookies and not token:
            return False, "Аккаунт не привязан"

        try:
            numeric_item_id = int(str(item_id).strip())
        except ValueError:
            return False, f"Некорректный ID объявления: {item_id}"

        proxies = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None
        headers = self._build_headers(item_url, token)

        async with AsyncSession(impersonate="chrome124", proxies=proxies, timeout=25) as session:
            try:
                await session.get(item_url, cookies=cookies, headers={"Referer": "https://www.avito.ru/"})
            except Exception:
                pass

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
                try:
                    resp = await session.post(url, json=payload, cookies=cookies, headers=headers)
                    last_status = resp.status_code

                    if resp.status_code in (401, 403):
                        return False, "Сессия отклонена (401/403). Перепривяжите через единый прокси."
                    if resp.status_code == 429:
                        return False, "Лимит запросов (429) на IP прокси."
                    if resp.status_code in (200, 201):
                        data = resp.json()
                        if mode == "direct":
                            return True, "Сообщение отправлено"
                        channel_id = (
                            data.get("channel", {}).get("id")
                            or data.get("result", {}).get("channel", {}).get("id")
                            or data.get("id")
                            or data.get("channelId")
                        )
                        if channel_id:
                            break
                except Exception as e:
                    logger.debug("Ошибка запроса к %s: %s", url, e)

            if not channel_id:
                return False, f"Диалог недоступен (HTTP {last_status or 'ERR'})."

            for send_url, send_payload in (
                (
                    "https://www.avito.ru/web/1/messenger/sendTextMessage",
                    {"channelId": channel_id, "text": text, "randomId": f"sniper_{numeric_item_id}"},
                ),
                (
                    f"https://www.avito.ru/web/1/messenger/channels/{channel_id}/messages",
                    {"type": "text", "message": {"text": text}},
                ),
            ):
                try:
                    s_resp = await session.post(send_url, json=send_payload, cookies=cookies, headers=headers)
                    if s_resp.status_code in (200, 201):
                        return True, "Сообщение отправлено"
                    last_status = s_resp.status_code
                except Exception as e:
                    logger.debug("Ошибка отправки текста в %s: %s", send_url, e)

            return False, f"Текст не доставлен (HTTP {last_status or 'ERR'})."
"""Отправка сообщений продавцу и проверка сессии Авито.

ВАЖНО: у Авито нет публичного API, который позволяет покупателю начать чат по объявлению
(официальный api.avito.ru умеет только отвечать в уже существующих чатах). Поэтому здесь
используются внутренние адреса сайта. Они не документированы и могут меняться: все адреса
собраны в константах CHANNEL_ENDPOINTS и SEND_ENDPOINTS ниже, при смене достаточно поправить их.
Каждый шаг пишется в лог (статус и начало ответа), так что причину сбоя видно в консоли.
"""
import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Any

from services.proxy_helper import create_browser_session, get_proxy_candidates, is_proxy_error, redact
from services.search_url import validate_avito_url

logger = logging.getLogger(__name__)

# Хотя бы один из этих ключей должен быть в cookies, иначе это не сессия Авито.
SESSION_KEYS = {"sessid", "u"}
# Ключи, которые показываем пользователю (остальные cookies тоже сохраняются и отправляются).
DISPLAY_KEYS = ("sessid", "u", "v", "auth", "srv_id", "ft", "f", "sx", "buyer_location_id")
MAX_COOKIES = 150
MAX_COOKIE_VALUE = 4096

# Шаг 1: создать чат по объявлению.
CHANNEL_ENDPOINTS = (
    "https://www.avito.ru/web/1/messenger/createChannelByItemId",
    "https://www.avito.ru/web/2/messenger/createChannelByItemId",
)
# Шаг 2: отправить текст в созданный чат.
SEND_ENDPOINTS = (
    "https://www.avito.ru/web/1/messenger/sendTextMessage",
    "https://www.avito.ru/web/1/messenger/channels/{channel_id}/messages",
)
DIRECT_ENDPOINT = "https://www.avito.ru/web/1/items/{item_id}/messenger/send"


# ---------------------------------------------------------------- cookies
def _clean_pair(name: object, value: object) -> tuple[str, str] | None:
    k = str(name or "").strip()
    v = str(value if value is not None else "").strip()
    if not k or not v or len(v) > MAX_COOKIE_VALUE or any(c in k for c in " ;=\r\n\t"):
        return None
    return k, v


def _domain_ok(domain: object) -> bool:
    d = str(domain or "").strip().lower()
    return (not d) or d.lstrip(".").endswith("avito.ru")


def parse_cookies(raw: Any) -> dict[str, str]:
    """Разбирает cookies из JSON Cookie-Editor, строки заголовка Cookie, cookies.txt или словаря.
    Возвращает ВСЕ cookies домена avito.ru (антибот-токены Авито тоже нужны для отправки)."""
    result: dict[str, str] = {}

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return result
        if text[0] in "[{":
            try:
                return parse_cookies(json.loads(text))
            except json.JSONDecodeError:
                pass

        for block in re.findall(r"\{[^{}]+\}", text):
            name_m = re.search(r'"name"\s*:\s*"([^"]+)"', block)
            val_m = re.search(r'"value"\s*:\s*"([^"]*)"', block)
            dom_m = re.search(r'"domain"\s*:\s*"([^"]*)"', block)
            if name_m and val_m and _domain_ok(dom_m.group(1) if dom_m else ""):
                pair = _clean_pair(name_m.group(1), val_m.group(1))
                if pair:
                    result[pair[0]] = pair[1]

        for line in text.splitlines():
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 7 and _domain_ok(parts[0].replace("#HttpOnly_", "")):
                pair = _clean_pair(parts[5], parts[6])
                if pair:
                    result[pair[0]] = pair[1]

        if not result and "{" not in text:
            for part in text.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    pair = _clean_pair(k, v)
                    if pair:
                        result[pair[0]] = pair[1]
        return dict(list(result.items())[:MAX_COOKIES])

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and _domain_ok(item.get("domain")):
                pair = _clean_pair(item.get("name"), item.get("value"))
                if pair:
                    result[pair[0]] = pair[1]
        return dict(list(result.items())[:MAX_COOKIES])

    if isinstance(raw, dict):
        if "name" in raw and "value" in raw and isinstance(raw.get("name"), str):
            if _domain_ok(raw.get("domain")):
                pair = _clean_pair(raw["name"], raw["value"])
                if pair:
                    result[pair[0]] = pair[1]
            return result
        for k, v in raw.items():
            if isinstance(v, (str, int)):
                pair = _clean_pair(k, v)
                if pair:
                    result[pair[0]] = pair[1]
        return dict(list(result.items())[:MAX_COOKIES])

    return result


def normalize_cookies(raw: Any) -> dict[str, str]:
    """Cookies для отправки. Пустой словарь, если среди них нет ключей сессии (sessid или u)."""
    cookies = parse_cookies(raw)
    return cookies if SESSION_KEYS & set(cookies) else {}


def display_keys(cookies: dict[str, str]) -> str:
    shown = [k for k in DISPLAY_KEYS if k in cookies]
    extra = len(cookies) - len(shown)
    text = ", ".join(shown)
    return f"{text} и ещё {extra}" if extra > 0 else text


# ---------------------------------------------------------------- ответы Авито
def _body_state(resp: Any) -> tuple[str, Any]:
    """('json', данные) | ('empty', None) | ('html', None) | ('bad', None)."""
    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        return "empty", None
    if text.startswith("<"):
        return "html", None
    try:
        return "json", json.loads(text)
    except (ValueError, TypeError):
        return "bad", None


def _has_error(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("error"):
        return True
    status = str(data.get("status", "")).lower()
    if status in ("error", "fail", "failed"):
        return True
    result = data.get("result")
    return isinstance(result, dict) and bool(result.get("error"))


def _extract_channel_id(data: Any) -> str | None:
    """Достаёт id чата из ответов вида {channel: {id}}, {result: {channel: {id}}}, {id}, {channelId}."""
    if not isinstance(data, dict):
        return None
    holders = [data]
    for key in ("result", "channel"):
        if isinstance(data.get(key), dict):
            holders.append(data[key])
    if isinstance(data.get("result"), dict) and isinstance(data["result"].get("channel"), dict):
        holders.append(data["result"]["channel"])
    for holder in holders:
        for key in ("channelId", "channel_id", "id"):
            value = holder.get(key)
            if value and isinstance(value, (str, int)) and not isinstance(value, bool):
                return str(value)
    return None


def _snippet(resp: Any) -> str:
    return (getattr(resp, "text", "") or "")[:160].replace("\n", " ")


@dataclass
class SendOutcome:
    ok: bool
    info: str
    security_alert: bool = False   # 401/403: автоотклик нужно остановить
    rate_limited: bool = False     # 429: сделать паузу
    retryable: bool = False        # сбой до отправки текста, можно повторить без риска дубля


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
            return False, "Не найдены ключевые cookies Авито (sessid или u)."

        headers = self._build_headers("https://www.avito.ru/profile")
        last_err = ""

        for proxies in get_proxy_candidates():
            try:
                async with create_browser_session(proxies, timeout=20) as session:
                    resp = await session.get("https://www.avito.ru/web/1/profile/short", cookies=cookies, headers=headers)
                    status = resp.status_code
                    if status == 200:
                        kind, data = _body_state(resp)
                        if kind == "json" and isinstance(data, dict):
                            name = data.get("name") or (data.get("user") or {}).get("name") or "Профиль Avito"
                            return True, f"Аккаунт подключён и активен: {name}"
                    elif status == 429:
                        return False, "IP упёрся в лимит Авито (HTTP 429). Подождите или смените IP."
                    elif status == 403:
                        return False, "Блок смены IP или WAF (HTTP 403). Запускайте бота с того же IP, где входили в аккаунт."
                    elif status == 401:
                        return False, "Сессия устарела (HTTP 401). Войдите в Avito заново и обновите cookies."

                    page = await session.get(
                        "https://www.avito.ru/profile",
                        cookies=cookies,
                        headers={
                            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                            "Sec-Fetch-Dest": "document",
                            "Sec-Fetch-Mode": "navigate",
                            "Sec-Fetch-Site": "same-origin",
                        },
                        allow_redirects=False,
                    )
                    if page.status_code == 200:
                        return True, "Сессия выглядит активной (проверено по странице профиля)."
                    if page.status_code in (301, 302, 303, 307, 308):
                        loc = str((getattr(page, "headers", {}) or {}).get("location", "")).lower()
                        if "login" in loc or "auth" in loc or "sign" in loc:
                            return False, "Сессия не активна: Авито просит войти заново. Обновите cookies."
                    if page.status_code in (401, 403):
                        return False, f"Авито не принял сессию (HTTP {page.status_code}). Обновите cookies."
                    return False, f"Не удалось подтвердить сессию (HTTP {status}/{page.status_code}). Cookies сохранены, проверьте отправкой."
            except Exception as e:
                last_err = redact(e)
                if is_proxy_error(last_err):
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
        """Совместимая обёртка: (успех, описание, тревога_безопасности_401_403)."""
        out = await self.send_message_ex(item_id, item_url, text, cookies_json)
        return out.ok, out.info, out.security_alert

    async def send_message_ex(
        self,
        item_id: int | str,
        item_url: str,
        text: str,
        cookies_json: str | None = None,
    ) -> SendOutcome:
        cookies = normalize_cookies(cookies_json or "")
        if not cookies:
            return SendOutcome(False, "Аккаунт Avito не привязан")
        if not (text or "").strip():
            return SendOutcome(False, "Пустой текст сообщения")

        try:
            numeric_item_id = int(str(item_id).strip())
        except ValueError:
            return SendOutcome(False, f"Некорректный ID объявления: {item_id}")

        item_url = validate_avito_url(item_url) or f"https://www.avito.ru/items/{numeric_item_id}"
        headers = self._build_headers(item_url)
        last_err = ""

        for proxies in get_proxy_candidates():
            text_stage = False
            try:
                async with create_browser_session(proxies, timeout=25) as session:
                    # 1. Открываем карточку, как человек перед нажатием «Написать»
                    page_status: int | None = None
                    try:
                        page = await session.get(
                            item_url,
                            cookies=cookies,
                            headers={
                                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                                "Referer": "https://www.avito.ru/",
                                "Sec-Fetch-Dest": "document",
                                "Sec-Fetch-Mode": "navigate",
                                "Sec-Fetch-Site": "same-origin",
                            },
                        )
                        page_status = page.status_code
                    except Exception as e:
                        if is_proxy_error(e):
                            raise
                        logger.info("Avito send %s: страница объявления не открылась (%s)", numeric_item_id, redact(e)[:100])

                    if page_status in (404, 410):
                        return SendOutcome(False, "Объявление уже снято (страница недоступна).")
                    if page_status == 429:
                        return SendOutcome(False, "Лимит запросов (HTTP 429). Пауза перед следующей отправкой.", rate_limited=True)
                    if page_status in (401, 403):
                        logger.warning("Avito send %s: страница объявления вернула %s", numeric_item_id, page_status)
                        return SendOutcome(False, f"Защита Avito ({page_status}): автоотклик остановлен для сохранения аккаунта.", security_alert=True)

                    await asyncio.sleep(random.uniform(1.5, 3.0))

                    # 2. Создаём чат по объявлению
                    channel_id: str | None = None
                    last_status: int | None = None
                    for url in CHANNEL_ENDPOINTS:
                        resp = await session.post(url, json={"itemId": numeric_item_id}, cookies=cookies, headers=headers)
                        last_status = resp.status_code
                        kind, data = _body_state(resp)
                        logger.info("Avito send %s: %s -> %s (%s) %s", numeric_item_id, url.rsplit("/", 3)[-3:], resp.status_code, kind, "" if resp.status_code in (200, 201) else _snippet(resp))

                        if resp.status_code in (401, 403):
                            return SendOutcome(False, f"Защита Avito ({resp.status_code}): автоотклик остановлен для сохранения аккаунта.", security_alert=True)
                        if resp.status_code == 429:
                            return SendOutcome(False, "Лимит запросов (HTTP 429). Пауза перед следующей отправкой.", rate_limited=True)
                        if resp.status_code == 400:
                            body = (resp.text or "").lower()
                            if "closed" in body or "disabled" in body or "недоступ" in body:
                                return SendOutcome(False, "Продавец отключил сообщения в этом объявлении.")
                        if resp.status_code in (200, 201) and kind == "json" and not _has_error(data):
                            channel_id = _extract_channel_id(data)
                            if channel_id:
                                break

                    if not channel_id:
                        text_stage = True
                        d_resp = await session.post(
                            DIRECT_ENDPOINT.format(item_id=numeric_item_id),
                            json={"message": {"text": text}, "type": "text"},
                            cookies=cookies,
                            headers=headers,
                        )
                        kind, data = _body_state(d_resp)
                        logger.info("Avito send %s: прямая отправка -> %s (%s) %s", numeric_item_id, d_resp.status_code, kind, "" if d_resp.status_code in (200, 201) else _snippet(d_resp))
                        if d_resp.status_code in (200, 201) and kind == "json" and not _has_error(data):
                            return SendOutcome(True, "Сообщение доставлено продавцу")
                        if d_resp.status_code in (401, 403):
                            return SendOutcome(False, f"Защита Avito ({d_resp.status_code}): автоотклик остановлен для сохранения аккаунта.", security_alert=True)
                        if d_resp.status_code == 429:
                            return SendOutcome(False, "Лимит запросов (HTTP 429). Пауза перед следующей отправкой.", rate_limited=True)
                        if d_resp.status_code >= 500:
                            return SendOutcome(False, f"Avito ответил ошибкой сервера (HTTP {d_resp.status_code}) при отправке. Повтор не делаю, чтобы не было дубля.")
                        text_stage = False

                    if not channel_id:
                        if last_status == 404:
                            return SendOutcome(False, "Чат создать не удалось (HTTP 404): объявление снято или Авито изменил адрес API.")
                        retry = bool(last_status and last_status >= 500)
                        return SendOutcome(False, f"Не удалось создать чат (HTTP {last_status or 'ERR'}).", retryable=retry)

                    # 3. Отправляем текст.
                    text_stage = True
                    for send_url in SEND_ENDPOINTS:
                        url = send_url.format(channel_id=channel_id)
                        if url.endswith("sendTextMessage"):
                            payload: dict[str, Any] = {
                                "channelId": channel_id,
                                "text": text,
                                "randomId": f"sniper_{numeric_item_id}_{random.randint(100000, 999999)}",
                            }
                        else:
                            payload = {"type": "text", "message": {"text": text}}

                        s_resp = await session.post(url, json=payload, cookies=cookies, headers=headers)
                        kind, data = _body_state(s_resp)
                        logger.info("Avito send %s: отправка текста -> %s (%s) %s", numeric_item_id, s_resp.status_code, kind, "" if s_resp.status_code in (200, 201) else _snippet(s_resp))
                        if s_resp.status_code in (200, 201) and kind in ("json", "empty") and not _has_error(data):
                            return SendOutcome(True, "Сообщение доставлено продавцу")
                        if s_resp.status_code in (401, 403):
                            return SendOutcome(False, f"Защита Avito ({s_resp.status_code}) при отправке.", security_alert=True)
                        if s_resp.status_code == 429:
                            return SendOutcome(False, "Лимит запросов (HTTP 429). Пауза перед следующей отправкой.", rate_limited=True)
                        last_status = s_resp.status_code

                    return SendOutcome(False, f"Чат открыт, но текст не принят (HTTP {last_status or 'ERR'}).")
            except Exception as e:
                last_err = redact(e)
                if is_proxy_error(last_err):
                    continue
                logger.warning("Avito send %s: ошибка сети: %s", numeric_item_id, last_err[:200])
                return SendOutcome(False, f"Ошибка сети при отправке: {last_err[:120]}", retryable=not text_stage)

        return SendOutcome(False, f"Ошибка сети при отправке: {last_err[:120]}", retryable=True)

import asyncio
import json
import logging
import random
from datetime import datetime
import aiohttp
from config import settings
from database import models

try:
    from curl_cffi.requests import AsyncSession as CurlAsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

logger = logging.getLogger(__name__)


def _is_night_time() -> bool:
    hour = datetime.now().hour
    return 0 <= hour < 7


async def send_first_message(item_id: str, text: str, seller_id: str = "unknown") -> tuple[bool, str]:
    """
    Отправляет сообщение продавцу с соблюдением лимитов антибана.
    Поддерживает:
    1. Официальный API Авито (если заданы AVITO_USER_ID и AVITO_ACCESS_TOKEN).
    2. Пользовательскую сессию по cookies, загруженным в меню бота (через curl_cffi).
    """
    night_mode = await models.get_setting("night_mode", "0") == "1"
    if night_mode and _is_night_time():
        return False, "Активен ночной режим (00:00–07:00)"

    hourly_limit = int(await models.get_setting("hourly_limit", "15"))
    sent_last_hour = await models.get_sent_count_last_hour()
    if sent_last_hour >= hourly_limit:
        return False, f"Достигнут лимит сообщений в час ({sent_last_hour}/{hourly_limit})"

    await asyncio.sleep(random.uniform(1.5, 4.0))
    proxy = settings.PROXY_URL

    # Вариант 1: Официальный Avito Messenger API
    if settings.AVITO_ACCESS_TOKEN and settings.AVITO_USER_ID:
        api_url = (
            f"https://api.avito.ru/messenger/v1/accounts/"
            f"{settings.AVITO_USER_ID}/chats/{item_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {settings.AVITO_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {"message": {"text": text}, "type": "text"}
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(api_url, json=payload, proxy=proxy) as resp:
                    if resp.status in (200, 201):
                        await models.log_sent_message(item_id, seller_id)
                        return True, "Отправлено через Avito API"
                    body = await resp.text()
                    return False, f"Ошибка Avito API ({resp.status}): {body[:120]}"
        except Exception as e:
            return False, f"Сетевая ошибка API: {type(e).__name__}: {e}"

    # Вариант 2: Привязанный аккаунт по Cookies из меню бота
    account = await models.get_account()
    if not account or not account.get("cookies_json"):
        return False, "Аккаунт Avito не привязан (загрузите cookies или токен)"

    if not account.get("is_valid"):
        return False, "Сессия Avito устарела — обновите cookies"

    try:
        cookies_dict = json.loads(account["cookies_json"])
    except Exception:
        return False, "Поврежденный формат cookies в БД"

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.avito.ru",
        "Referer": f"https://www.avito.ru/items/{item_id}",
    }

    session_check_url = "https://www.avito.ru/web/1/profile/short"
    msg_url = f"https://www.avito.ru/web/1/messenger/items/{item_id}/chat"

    try:
        if HAS_CURL_CFFI:
            async with CurlAsyncSession(impersonate="chrome", timeout=15) as session:
                check_resp = await session.get(
                    session_check_url, headers=headers, cookies=cookies_dict, proxy=proxy
                )
                if check_resp.status_code in (401, 403):
                    await models.set_account_validity(0)
                    return False, "Сессия cookies истекла (401/403). Загрузите новые cookies!"

                resp = await session.post(
                    msg_url, json={"text": text}, headers=headers, cookies=cookies_dict, proxy=proxy
                )
                if resp.status_code in (200, 201):
                    await models.log_sent_message(item_id, seller_id)
                    return True, "Сообщение отправлено первым"
                if resp.status_code in (401, 403):
                    await models.set_account_validity(0)
                    return False, "Сессия cookies истекла (401/403). Обновите cookies!"
                logger.warning("Avito messenger status %s: %s", resp.status_code, resp.text[:200])
                return False, f"Продавец закрыл сообщения или изменился эндпоинт (HTTP {resp.status_code})"

        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        async with aiohttp.ClientSession(
            headers=headers, cookies=cookies_dict, timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            async with session.get(session_check_url, proxy=proxy) as check_resp:
                if check_resp.status in (401, 403):
                    await models.set_account_validity(0)
                    return False, "Сессия cookies истекла (401/403). Загрузите новые cookies!"

            async with session.post(msg_url, json={"text": text}, proxy=proxy) as resp:
                if resp.status in (200, 201):
                    await models.log_sent_message(item_id, seller_id)
                    return True, "Сообщение отправлено первым"
                if resp.status in (401, 403):
                    await models.set_account_validity(0)
                    return False, "Сессия cookies истекла (401/403). Обновите cookies!"
                return False, f"Продавец закрыл сообщения или изменился эндпоинт (HTTP {resp.status})"
    except Exception as e:
        logger.error("Ошибка при отправке сообщения по объявлению %s: %s (%s)", item_id, type(e).__name__, e)
        return False, f"Ошибка соединения: {type(e).__name__}"

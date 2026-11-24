import logging
import re
import statistics
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from config import settings
from services.avito_messenger import normalize_cookies

logger = logging.getLogger(__name__)


def _ensure_sorted_by_date(url: str) -> str:
    if "s=104" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}s=104"


async def parse_avito_search(search_url: str, search_name: str = "", cookies_json: str | None = None) -> list[dict]:
    url = _ensure_sorted_by_date(search_url.strip())
    proxies = {"http": settings.PROXY_URL, "https": settings.PROXY_URL} if settings.PROXY_URL else None
    cookies = normalize_cookies(cookies_json or "")

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        async with AsyncSession(impersonate="chrome124", proxies=proxies, timeout=25) as session:
            resp = await session.get(url, headers=headers, cookies=cookies)
            if resp.status_code != 200:
                logger.warning("Avito вернул статус %s для поиска '%s'", resp.status_code, search_name or url)
                return []
            html = resp.text
    except Exception as e:
        logger.error("Ошибка curl_cffi при парсинге '%s': %s", search_name or url, e)
        return []

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select('[data-marker="item"]')
    items: list[dict] = []

    for card in cards:
        item_id = card.get("data-item-id")
        if not item_id:
            continue

        title_el = card.select_one('[itemprop="name"], [data-marker="item-title"]')
        title = title_el.get_text(strip=True) if title_el else f"Объявление #{item_id}"

        link_el = card.select_one('a[data-marker="item-title"], a[itemprop="url"]')
        href = link_el.get("href", "") if link_el else ""
        if href.startswith("/"):
            item_url = f"https://www.avito.ru{href}"
        elif href.startswith("http"):
            item_url = href
        else:
            item_url = f"https://www.avito.ru/items/{item_id}"

        price_val: int | None = None
        price_meta = card.select_one('meta[itemprop="price"]')
        if price_meta and price_meta.get("content"):
            digits = re.sub(r"\D", "", str(price_meta["content"]))
            if digits:
                price_val = int(digits)
        else:
            price_el = card.select_one('[data-marker="item-price"]')
            if price_el:
                digits = re.sub(r"\D", "", price_el.get_text())
                if digits:
                    price_val = int(digits)

        desc_el = card.select_one('meta[itemprop="description"], [class*="item-description"]')
        if desc_el:
            description = desc_el.get("content") or desc_el.get_text(" ", strip=True)
        else:
            description = ""

        loc_el = card.select_one('[data-marker="item-location"], [class*="geo-root"]')
        location = loc_el.get_text(" ", strip=True) if loc_el else "Не указано"

        img_el = card.select_one("img")
        image_url = None
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src")

        seller_id = None
        seller_link = card.select_one('a[href*="/user/"], a[href*="/brands/"]')
        if seller_link and seller_link.get("href"):
            m = re.search(r"/(?:user|brands)/([^/?]+)", seller_link["href"])
            if m:
                seller_id = m.group(1)

        seller_type = "Магазин / Компания" if card.select_one('[data-marker="item-badge-company"]') else "Частное лицо"

        items.append(
            {
                "id": str(item_id),
                "title": title,
                "url": item_url,
                "price": price_val,
                "description": description,
                "location": location,
                "image_url": image_url,
                "seller_id": seller_id,
                "seller_type": seller_type,
                "discount_pct": 0,
            }
        )

    valid_prices = [x["price"] for x in items if x["price"] and x["price"] > 100]
    if len(valid_prices) >= 5:
        median_price = statistics.median(valid_prices)
        for x in items:
            if x["price"] and median_price > 0 and x["price"] < median_price:
                pct = int(round((1 - x["price"] / median_price) * 100))
                if pct >= 10:
                    x["discount_pct"] = pct

    return items
import logging
import re
from dataclasses import dataclass
from typing import Any
import aiohttp
from bs4 import BeautifulSoup
from config import settings
from database import models

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


@dataclass
class AvitoItem:
    item_id: str
    title: str
    price: int
    url: str
    description: str
    image_url: str | None
    seller_id: str
    is_company: bool
    location: str


def _extract_digits(text: str) -> int:
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else 0


async def fetch_search_items(search: dict[str, Any]) -> list[AvitoItem]:
    """Загружает страницу выдачи Авито и извлекает карточки объявлений."""
    url = search["url"]
    timeout = aiohttp.ClientTimeout(total=15)

    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=timeout) as session:
            async with session.get(url, proxy=settings.PROXY_URL or None) as resp:
                if resp.status != 200:
                    logger.warning("Avito вернул статус %s для поиска '%s'", resp.status, search["name"])
                    return []
                html = await resp.text()
    except Exception as e:
        logger.error("Ошибка HTTP при парсинге '%s': %s", search["name"], e)
        return []

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select('[data-marker="item"]')
    items: list[AvitoItem] = []

    for card in cards:
        item_id = card.get("data-item-id") or ""
        if not item_id:
            continue

        title_el = card.select_one('[itemprop="name"], [data-marker="item-title"]')
        title = title_el.get_text(strip=True) if title_el else "Без названия"

        link_el = card.select_one('a[data-marker="item-title"], a[itemprop="url"]')
        href = link_el.get("href", "") if link_el else ""
        if href.startswith("/"):
            item_url = "https://www.avito.ru" + href.split("?")[0]
        elif href.startswith("http"):
            item_url = href.split("?")[0]
        else:
            item_url = f"https://www.avito.ru/items/{item_id}"

        price_meta = card.select_one('meta[itemprop="price"]')
        if price_meta and price_meta.get("content"):
            price = _extract_digits(price_meta["content"])
        else:
            price_el = card.select_one('[data-marker="item-price"]')
            price = _extract_digits(price_el.get_text() if price_el else "")

        desc_el = card.select_one('meta[itemprop="description"], [class*="item-description"]')
        if desc_el:
            description = (
                desc_el.get("content", "").strip()
                if desc_el.name == "meta"
                else desc_el.get_text(" ", strip=True)
            )
        else:
            description = ""

        img_el = card.select_one("img")
        image_url = None
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src")

        loc_el = card.select_one('[data-marker="item-address"], [class*="geo-root"]')
        location = loc_el.get_text(" ", strip=True) if loc_el else ""

        seller_link = card.select_one('a[href*="/user/"], a[href*="/brands/"]')
        seller_id = "unknown"
        is_company = False
        if seller_link:
            s_href = seller_link.get("href", "")
            if "/brands/" in s_href:
                is_company = True
            parts = [p for p in s_href.split("/") if p]
            if len(parts) >= 2:
                seller_id = parts[1][:32]

        if card.select_one('[data-marker="badge-title"]'):
            badge_text = card.select_one('[data-marker="badge-title"]').get_text(strip=True).lower()
            if "компания" in badge_text or "магазин" in badge_text:
                is_company = True

        items.append(
            AvitoItem(
                item_id=str(item_id),
                title=title,
                price=price,
                url=item_url,
                description=description[:400],
                image_url=image_url,
                seller_id=seller_id,
                is_company=is_company,
                location=location,
            )
        )

    return items


async def passes_filters(item: AvitoItem, search: dict[str, Any]) -> bool:
    """Проверяет объявление по цене, минус-словам, плюс-словам, частникам и ЧС."""
    if await models.is_blacklisted(item.seller_id):
        return False

    if search["only_private"] and item.is_company:
        return False

    min_p = search["min_price"] or 0
    max_p = search["max_price"] or 0
    if min_p > 0 and item.price < min_p:
        return False
    if max_p > 0 and item.price > max_p:
        return False

    haystack = f"{item.title} {item.description}".lower()

    if search["stop_words"]:
        stops = [w.strip().lower() for w in search["stop_words"].split(",") if w.strip()]
        if any(sw in haystack for sw in stops):
            return False

    if search["plus_words"]:
        pluses = [w.strip().lower() for w in search["plus_words"].split(",") if w.strip()]
        if pluses and not any(pw in haystack for pw in pluses):
            return False

    return True

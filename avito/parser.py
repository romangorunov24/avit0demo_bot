from __future__ import annotations

import html as html_lib
import json
import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urljoin, urlparse, urlunparse

from lxml import html as lxml_html

from database.models import AvitoItem, SearchTask

logger = logging.getLogger(__name__)

CITY_SLUGS: dict[str, str] = {
    "россия": "rossiya",
    "вся россия": "rossiya",
    "москва": "moskva",
    "санкт-петербург": "sankt-peterburg",
    "спб": "sankt-peterburg",
    "питер": "sankt-peterburg",
    "краснодар": "krasnodar",
    "сочи": "sochi",
    "туапсе": "tuapse",
    "ростов-на-дону": "rostov-na-donu",
    "ростов": "rostov-na-donu",
    "екатеринбург": "ekaterinburg",
    "новосибирск": "novosibirsk",
    "казань": "kazan",
    "нижний новгород": "nizhniy_novgorod",
    "самара": "samara",
    "челябинск": "chelyabinsk",
    "омск": "omsk",
    "уфа": "ufa",
    "красноярск": "krasnoyarsk",
    "воронеж": "voronezh",
    "пермь": "perm",
    "волгоград": "volgograd",
    "тюмень": "tyumen",
    "ставрополь": "stavropol",
}


def resolve_region_slug(region_input: str) -> str:
    cleaned = (region_input or "").strip().lower()
    if not cleaned:
        return "rossiya"
    if cleaned in CITY_SLUGS:
        return CITY_SLUGS[cleaned]
    if re.fullmatch(r"[a-z0-9_-]+", cleaned):
        return cleaned
    return "rossiya"


def build_search_url(
    raw_url_or_query: str,
    region: str = "rossiya",
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
) -> str:
    """
    Собирает корректный URL поиска Avito с сортировкой по дате (s=104):
    - Если передана готовая ссылка avito.ru — нормализует её и добавляет s=104 (если не задана иная сортировка).
    - Если передан текстовый запрос — формирует URL поиска по выбранному региону и ценам.
    """
    text = raw_url_or_query.strip()

    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        if "avito.ru" not in parsed.netloc.lower():
            raise ValueError("Ссылка должна вести на сайт avito.ru")
        query_params = parse_qs(parsed.query, keep_blank_values=False)
        if "s" not in query_params:
            query_params["s"] = ["104"]
        if min_price is not None and "pmin" not in query_params:
            query_params["pmin"] = [str(min_price)]
        if max_price is not None and "pmax" not in query_params:
            query_params["pmax"] = [str(max_price)]
        new_query = urlencode(query_params, doseq=True)
        return urlunparse(
            (
                "https",
                "www.avito.ru",
                parsed.path or "/rossiya",
                "",
                new_query,
                "",
            )
        )

    slug = resolve_region_slug(region)
    params: dict[str, str] = {
        "q": text,
        "s": "104",
    }
    if min_price is not None and min_price > 0:
        params["pmin"] = str(min_price)
    if max_price is not None and max_price > 0:
        params["pmax"] = str(max_price)

    return f"https://www.avito.ru/{slug}?{urlencode(params, quote_via=quote_plus)}"


def _clean_price(raw_price: Any) -> tuple[int, str]:
    if isinstance(raw_price, (int, float)):
        val = int(raw_price)
        return val, f"{val:,} ₽".replace(",", " ") if val > 0 else "Цена не указана"
    if isinstance(raw_price, dict):
        val = raw_price.get("value") or raw_price.get("current") or 0
        try:
            int_val = int(val)
            text = raw_price.get("string") or (
                f"{int_val:,} ₽".replace(",", " ") if int_val > 0 else "Цена не указана"
            )
            return int_val, str(text)
        except (TypeError, ValueError):
            pass
    text = str(raw_price or "").strip()
    digits = re.sub(r"[^\d]", "", text)
    if digits:
        val = int(digits)
        return val, text if "₽" in text else f"{val:,} ₽".replace(",", " ")
    return 0, text or "Цена не указана"


def _walk_json_for_items(node: Any, collected: dict[str, AvitoItem]) -> None:
    """Рекурсивно ищет объекты объявлений Avito в JSON-дереве страницы."""
    if isinstance(node, list):
        for elem in node:
            _walk_json_for_items(elem, collected)
        return

    if not isinstance(node, dict):
        return

    raw_id = node.get("id")
    title = node.get("title")
    url_path = node.get("urlPath") or node.get("uri") or node.get("url")

    if raw_id and title and url_path and isinstance(title, str) and isinstance(url_path, str):
        item_id = str(raw_id).strip()
        if item_id.isdigit() and len(item_id) >= 6 and item_id not in collected:
            full_url = urljoin("https://www.avito.ru", url_path.split("?")[0])
            price_val, price_text = _clean_price(node.get("priceDetailed") or node.get("price"))

            city = ""
            geo = node.get("geo") or node.get("location") or {}
            if isinstance(geo, dict):
                city = str(
                    geo.get("formattedAddress")
                    or geo.get("name")
                    or (geo.get("city") or {}).get("name", "")
                ).strip()
            if not city:
                city = str(node.get("address") or node.get("cityName") or "").strip()

            seller_id = ""
            seller_name = ""
            iva = node.get("iva") or {}
            user_info = node.get("user") or node.get("seller") or {}
            if isinstance(user_info, dict):
                seller_id = str(user_info.get("id") or user_info.get("publicId") or "").strip()
                seller_name = str(user_info.get("name") or user_info.get("title") or "").strip()
            if not seller_id and node.get("userId"):
                seller_id = str(node["userId"]).strip()

            image_url = ""
            images = node.get("images") or (node.get("gallery") or {}).get("items") or []
            if isinstance(images, list) and images:
                first_img = images[0]
                if isinstance(first_img, dict):
                    for key in ("640x480", "432x324", "208x156", "url", "src"):
                        if first_img.get(key):
                            image_url = str(first_img[key])
                            break
                elif isinstance(first_img, str):
                    image_url = first_img

            is_promoted = bool(
                node.get("isPromotion")
                or node.get("promoted")
                or (isinstance(iva, dict) and "Vas" in str(iva))
            )

            collected[item_id] = AvitoItem(
                item_id=item_id,
                title=html_lib.unescape(title).strip(),
                price=price_val,
                price_text=price_text,
                url=full_url,
                city=city,
                seller_id=seller_id,
                seller_name=seller_name,
                description=html_lib.unescape(str(node.get("description") or "")).strip()[:500],
                image_url=image_url,
                is_promoted=is_promoted,
                published_text=str(node.get("sortTimeStamp") or node.get("time") or ""),
            )

    for v in node.values():
        if isinstance(v, (dict, list)):
            _walk_json_for_items(v, collected)


def _extract_from_embedded_json(html_text: str) -> list[AvitoItem]:
    collected: dict[str, AvitoItem] = {}

    init_matches = re.findall(
        r'window\.__initialData__\s*=\s*"([^"]+)"',
        html_text,
    )
    for raw_encoded in init_matches:
        try:
            decoded = unquote(raw_encoded)
            data = json.loads(decoded)
            _walk_json_for_items(data, collected)
        except Exception:
            continue

    if not collected:
        try:
            doc = lxml_html.fromstring(html_text)
            for script in doc.xpath("//script"):
                s_type = (script.get("type") or "").lower()
                raw_content = script.text_content() or ""
                if not raw_content.strip():
                    continue
                if "json" in s_type or "mime/invalid" in s_type or '"urlPath"' in raw_content:
                    candidate = raw_content.strip()
                    if candidate.startswith('"') and candidate.endswith('"'):
                        try:
                            candidate = unquote(json.loads(candidate))
                        except Exception:
                            pass
                    try:
                        data = json.loads(candidate)
                        _walk_json_for_items(data, collected)
                    except Exception:
                        continue
        except Exception:
            pass

    return list(collected.values())


def _extract_from_html_dom(html_text: str) -> list[AvitoItem]:
    """Резервный парсер DOM-карточек Avito через lxml.html."""
    try:
        doc = lxml_html.fromstring(html_text)
    except Exception:
        return []

    items: list[AvitoItem] = []
    seen_ids: set[str] = set()

    cards = doc.xpath('//*[@data-marker="item"]')
    for card in cards:
        item_id = str(card.get("data-item-id") or "").strip()
        if not item_id:
            id_attr = str(card.get("id") or "")
            m = re.search(r"(\d{6,})", id_attr)
            if m:
                item_id = m.group(1)
        if not item_id or item_id in seen_ids:
            continue

        title_nodes = card.xpath('.//*[@itemprop="name" or @data-marker="item-title"]')
        link_nodes = card.xpath('.//a[@itemprop="url" or @data-marker="item-title"]')
        if not title_nodes or not link_nodes:
            continue

        title = " ".join(title_nodes[0].text_content().split())
        href = str(link_nodes[0].get("href") or "").split("?")[0]
        if not href:
            continue
        full_url = urljoin("https://www.avito.ru", href)

        price_metas = card.xpath('.//meta[@itemprop="price"]')
        price_nodes = card.xpath('.//*[@data-marker="item-price"]')
        raw_price = (
            price_metas[0].get("content")
            if price_metas and price_metas[0].get("content")
            else (" ".join(price_nodes[0].text_content().split()) if price_nodes else "")
        )
        price_val, price_text = _clean_price(raw_price)

        addr_nodes = card.xpath('.//*[@data-marker="item-address"]')
        city = " ".join(addr_nodes[0].text_content().split()) if addr_nodes else ""

        desc_metas = card.xpath('.//meta[@itemprop="description"]')
        desc = str(desc_metas[0].get("content") or "").strip()[:500] if desc_metas else ""

        img_nodes = card.xpath(".//img")
        image_url = ""
        if img_nodes:
            image_url = str(img_nodes[0].get("src") or img_nodes[0].get("data-src") or "")

        seen_ids.add(item_id)
        items.append(
            AvitoItem(
                item_id=item_id,
                title=title,
                price=price_val,
                price_text=price_text,
                url=full_url,
                city=city,
                description=desc,
                image_url=image_url,
            )
        )

    return items


def parse_search_page(html_text: str) -> list[AvitoItem]:
    """Извлекает список объявлений со страницы поиска Avito (JSON + DOM fallback)."""
    if not html_text:
        return []
    items = _extract_from_embedded_json(html_text)
    if not items:
        items = _extract_from_html_dom(html_text)
    return items


def filter_items(items: list[AvitoItem], task: SearchTask) -> list[AvitoItem]:
    """Фильтрует объявления по цене, обязательным словам и стоп-словам."""
    include_tokens = [w.strip().lower() for w in task.include_words.split(",") if w.strip()]
    exclude_tokens = [w.strip().lower() for w in task.exclude_words.split(",") if w.strip()]

    filtered: list[AvitoItem] = []
    for item in items:
        if task.min_price is not None and item.price > 0 and item.price < task.min_price:
            continue
        if task.max_price is not None and item.price > 0 and item.price > task.max_price:
            continue

        haystack = f"{item.title} {item.description}".lower()

        if include_tokens and not any(tok in haystack for tok in include_tokens):
            continue
        if exclude_tokens and any(tok in haystack for tok in exclude_tokens):
            continue

        filtered.append(item)

    return filtered

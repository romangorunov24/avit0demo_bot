import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def normalize_avito_url(raw_url: str) -> str:
    """Проверяет ссылку Авито и принудительно ставит сортировку по дате (s=104)."""
    url = raw_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if "avito.ru" not in parsed.netloc:
        raise ValueError("Ссылка должна вести на сайт avito.ru")
    query = parse_qs(parsed.query)
    query["s"] = ["104"]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def parse_cookies_json(raw_text: str) -> dict[str, str]:
    """Конвертирует JSON из Cookie-Editor (массив объектов) или словарь в dict."""
    data = json.loads(raw_text)
    cookies: dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "name" in item and "value" in item:
                cookies[str(item["name"])] = str(item["value"])
    elif isinstance(data, dict):
        cookies = {str(k): str(v) for k, v in data.items()}
    else:
        raise ValueError("Неверный формат JSON cookies.")

    if not cookies:
        raise ValueError("Список cookies пуст.")
    return cookies


def calc_discount_percent(price: int, avg_price: float | None) -> int | None:
    if not avg_price or avg_price <= 0 or price <= 0:
        return None
    diff = ((avg_price - price) / avg_price) * 100
    return round(diff) if diff >= 5 else None

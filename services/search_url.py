"""Сборка и проверка ссылок поиска Авито."""
from urllib.parse import quote_plus, urlparse

# slug города в адресе Авито -> (название для кнопки, варианты написания для текстового ввода)
CITIES: dict[str, tuple[str, list[str]]] = {
    "moskva": ("Москва", ["москва", "мск"]),
    "sankt-peterburg": ("Санкт-Петербург", ["санкт-петербург", "спб", "питер", "петербург"]),
    "novosibirsk": ("Новосибирск", ["новосибирск"]),
    "ekaterinburg": ("Екатеринбург", ["екатеринбург", "екб"]),
    "kazan": ("Казань", ["казань"]),
    "nizhniy_novgorod": ("Нижний Новгород", ["нижний новгород", "нижний"]),
    "chelyabinsk": ("Челябинск", ["челябинск"]),
    "samara": ("Самара", ["самара"]),
    "omsk": ("Омск", ["омск"]),
    "rostov-na-donu": ("Ростов-на-Дону", ["ростов-на-дону", "ростов"]),
    "ufa": ("Уфа", ["уфа"]),
    "krasnoyarsk": ("Красноярск", ["красноярск"]),
    "voronezh": ("Воронеж", ["воронеж"]),
    "perm": ("Пермь", ["пермь"]),
    "volgograd": ("Волгоград", ["волгоград"]),
    "krasnodar": ("Краснодар", ["краснодар"]),
    "rossiya": ("Вся Россия", ["вся россия", "россия"]),
}

MEMORY_CHOICES = ["64", "128", "256", "512", "1024"]


def resolve_city(text: str) -> str | None:
    low = (text or "").strip().lower().replace("ё", "е")
    for slug, (_, aliases) in CITIES.items():
        if low == slug or low in [a.replace("ё", "е") for a in aliases]:
            return slug
    return None


def city_title(slug: str | None) -> str:
    if not slug:
        return "по ссылке"
    return CITIES.get(slug, (slug, []))[0]


def build_search_url(city_slug: str, model: str) -> str:
    query = quote_plus(" ".join((model or "").split())[:80])
    return f"https://www.avito.ru/{city_slug}/telefony?q={query}&s=104"


def validate_avito_url(url: str | None) -> str | None:
    """Пропускает только https-ссылки на avito.ru. Защита от запросов на посторонние адреса."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https"):
        return None
    if host != "avito.ru" and not host.endswith(".avito.ru"):
        return None
    if parsed.username or parsed.password:
        return None
    return parsed._replace(scheme="https").geturl()

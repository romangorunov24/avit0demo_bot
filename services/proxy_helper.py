from __future__ import annotations

from urllib.parse import urlparse, urlsplit, urlunsplit


ALLOWED_SCHEMES = ("http", "https", "socks4", "socks5", "socks5h")


def normalize_proxy(raw_proxy: str | None) -> str | None:
    """
    Приводит прокси из любого популярного формата к стандартному URL:
    - http://user:pass@ip:port
    - socks5://user:pass@ip:port
    - ip:port:user:pass -> http://user:pass@ip:port
    - user:pass@ip:port -> http://user:pass@ip:port
    - ip:port -> http://ip:port
    """
    if not raw_proxy:
        return None

    value = raw_proxy.strip()
    if not value:
        return None

    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise ValueError(f"Неподдерживаемый протокол прокси: {parsed.scheme}")
        if not parsed.hostname or not parsed.port:
            raise ValueError("Некорректный адрес или порт прокси")
        return value

    if "@" in value:
        candidate = f"http://{value}"
        parsed = urlparse(candidate)
        if not parsed.hostname or not parsed.port:
            raise ValueError("Некорректный формат прокси user:pass@ip:port")
        return candidate

    parts = value.split(":")
    if len(parts) == 2:
        host, port = parts[0].strip(), parts[1].strip()
        if not host or not port.isdigit():
            raise ValueError("Порт прокси должен быть числом")
        return f"http://{host}:{port}"

    if len(parts) == 4:
        host, port, user, password = (p.strip() for p in parts)
        if not host or not port.isdigit():
            raise ValueError("Некорректный формат ip:port:user:pass")
        return f"http://{user}:{password}@{host}:{port}"

    raise ValueError(
        "Не удалось распознать формат прокси. Используйте: "
        "http://user:pass@ip:port, socks5://user:pass@ip:port или ip:port:user:pass"
    )


def build_curl_proxies(proxy_url: str | None) -> dict[str, str] | None:
    """Формирует словарь прокси для curl_cffi AsyncSession."""
    normalized = normalize_proxy(proxy_url)
    if not normalized:
        return None
    return {
        "http": normalized,
        "https": normalized,
    }


def mask_proxy(proxy_url: str | None) -> str:
    """Скрывает пароль прокси при выводе в интерфейс бота."""
    if not proxy_url:
        return "Не установлен (прямое подключение)"
    parsed = urlsplit(proxy_url)
    if parsed.username and parsed.password and parsed.hostname:
        netloc = f"{parsed.username}:***@{parsed.hostname}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return proxy_url

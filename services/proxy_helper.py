import html
import re
from urllib.parse import quote

from curl_cffi.requests import AsyncSession
from config import settings

_CRED_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s]+@")


def redact(text: object) -> str:
    """Прячет логин и пароль прокси (scheme://user:pass@host) в тексте ошибок и логов."""
    return _CRED_RE.sub(r"\1***@", str(text))


def is_proxy_error(err: object) -> bool:
    """Ошибка именно соединения через прокси: стоит попробовать запасной тип прокси (HTTP <-> SOCKS5H)."""
    low = str(err).lower()
    return "proxy" in low or "(7)" in low or "(5)" in low or "(97)" in low or "(35)" in low


def get_proxy_candidates(raw_proxy: str | None = None) -> list[dict[str, str] | None]:
    """
    Принимает прокси в любом формате:
    - http://user:pass@host:port
    - socks5h://user:pass@host:port
    - host:port:user:pass
    - host:port
    Возвращает список кандидатов для автоматического переключения HTTP <-> SOCKS5H.
    """
    val = (raw_proxy if raw_proxy is not None else settings.PROXY_URL) or ""
    val = val.strip()
    if not val:
        return [None]

    scheme = None
    body = val
    if "://" in val:
        scheme, body = val.split("://", 1)
        scheme = scheme.lower()

    normalized = body
    # Формат host:port:user:password распознаём по началу «хост:порт:», даже если в пароле есть «@»
    if "@" not in body or re.match(r"^[^:@/\s]+:\d{1,5}:", body):
        parts = body.split(":", 3)
        if len(parts) == 4 and parts[1].isdigit():
            host, port, user, password = parts
            normalized = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"

    if scheme in ("socks5", "socks5h"):
        return [
            {"http": f"socks5h://{normalized}", "https": f"socks5h://{normalized}"},
            {"http": f"http://{normalized}", "https": f"http://{normalized}"},
        ]
    if scheme in ("http", "https"):
        return [
            {"http": f"http://{normalized}", "https": f"http://{normalized}"},
            {"http": f"socks5h://{normalized}", "https": f"socks5h://{normalized}"},
        ]

    # Если схема не указана явно — пробуем сначала HTTP, затем SOCKS5H
    return [
        {"http": f"http://{normalized}", "https": f"http://{normalized}"},
        {"http": f"socks5h://{normalized}", "https": f"socks5h://{normalized}"},
    ]


def create_browser_session(proxies: dict[str, str] | None, timeout: int = 20) -> AsyncSession:
    """Создаёт сессию с актуальным TLS-отпечатком Chrome."""
    try:
        return AsyncSession(impersonate="chrome", proxies=proxies, timeout=timeout)
    except Exception:
        return AsyncSession(impersonate="chrome124", proxies=proxies, timeout=timeout)


async def diagnose_connection() -> str:
    candidates = get_proxy_candidates()
    using_proxy = candidates[0] is not None
    last_err = ""

    for proxies in candidates:
        proto = "Прямое подключение (без прокси)" if not proxies else proxies["http"].split("://")[0].upper()
        try:
            ip_info = "неизвестен"
            country = "?"
            isp = ""

            async with create_browser_session(proxies, timeout=15) as ip_session:
                ip_resp = await ip_session.get("https://ipwho.is/")
                if ip_resp.status_code == 200:
                    j = ip_resp.json()
                    ip_info = j.get("ip") or ip_info
                    country = j.get("country_code") or "?"
                    isp = j.get("connection", {}).get("isp") or ""

            async with create_browser_session(proxies, timeout=20) as avito_session:
                avito_resp = await avito_session.get(
                    "https://www.avito.ru/",
                    headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
                )
                st = avito_resp.status_code

            geo_note = "✅ Отлично (IP из России)" if country == "RU" else "⚠️ Внимание: IP не из России (возможен блок Авито)"
            avito_note = "✅ Avito доступен (HTTP 200)" if st == 200 else f"❌ Avito вернул HTTP {st}"

            return (
                f"🌐 <b>Диагностика сети</b>\n\n"
                f"• Режим: <b>{proto}</b>\n"
                f"• Текущий IP: <code>{html.escape(str(ip_info))}</code> ({html.escape(str(country))})\n"
                f"• Провайдер: {html.escape(str(isp)) or 'не определён'}\n"
                f"• Гео-статус: {geo_note}\n"
                f"• Доступ к Avito: {avito_note}"
            )
        except Exception as e:
            last_err = f"{proto}: {redact(e)}"

    hint = (
        "Проверьте баланс трафика и порт в личном кабинете прокси, либо запустите бота локально на ПК в РФ с пустым PROXY_URL."
        if using_proxy
        else "Проверьте интернет-соединение на устройстве."
    )
    return (
        f"❌ <b>Ошибка сетевого соединения</b>\n\n"
        f"Детали: <code>{html.escape(last_err[:220])}</code>\n\n"
        f"💡 {hint}"
    )

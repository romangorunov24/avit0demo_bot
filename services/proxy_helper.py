from curl_cffi.requests import AsyncSession
from config import settings


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
    if "@" not in body:
        parts = body.split(":")
        if len(parts) == 4:
            host, port, user, password = parts
            normalized = f"{user}:{password}@{host}:{port}"
        elif len(parts) == 2:
            normalized = body

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


async def diagnose_connection() -> str:
    candidates = get_proxy_candidates()
    using_proxy = candidates[0] is not None
    last_err = ""

    for proxies in candidates:
        proto = "Прямое подключение (без прокси)" if not proxies else proxies["http"].split("://")[0].upper()
        try:
            async with AsyncSession(impersonate="chrome124", proxies=proxies, timeout=15) as session:
                ip_resp = await session.get("https://ipwho.is/")
                ip_info = "неизвестен"
                country = "?"
                isp = ""
                if ip_resp.status_code == 200:
                    j = ip_resp.json()
                    ip_info = j.get("ip") or ip_info
                    country = j.get("country_code") or "?"
                    isp = j.get("connection", {}).get("isp") or ""

                avito_resp = await session.get("https://www.avito.ru/")
                st = avito_resp.status_code

                geo_note = "✅ Отлично (IP из России)" if country == "RU" else "⚠️ Внимание: IP не из России (возможен блок Авито)"
                avito_note = "✅ Avito доступен (HTTP 200)" if st == 200 else f"❌ Avito вернул HTTP {st}"

                return (
                    f"🌐 <b>Диагностика сети</b>\n\n"
                    f"• Режим: <b>{proto}</b>\n"
                    f"• Текущий IP: <code>{ip_info}</code> ({country})\n"
                    f"• Провайдер: {isp or 'не определён'}\n"
                    f"• Гео-статус: {geo_note}\n"
                    f"• Доступ к Avito: {avito_note}"
                )
        except Exception as e:
            last_err = f"{proto}: {e}"

    hint = (
        "Проверьте баланс трафика и порт в личном кабинете прокси, либо запустите бота локально на ПК в РФ с пустым PROXY_URL."
        if using_proxy
        else "Проверьте интернет-соединение на устройстве."
    )
    return (
        f"❌ <b>Ошибка сетевого соединения</b>\n\n"
        f"Детали: <code>{last_err[:220]}</code>\n\n"
        f"💡 {hint}"
    )
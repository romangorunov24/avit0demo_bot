from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from curl_cffi.requests import AsyncSession

from avito.exceptions import (
    AvitoAuthError,
    AvitoProxyError,
    AvitoRateLimitError,
)
from services.proxy_helper import build_curl_proxies, mask_proxy

logger = logging.getLogger(__name__)

IMPERSONATE_CANDIDATES = ["chrome131", "chrome124", "chrome120", "chrome"]


@dataclass(slots=True)
class HttpResponseData:
    status_code: int
    text: str
    url: str
    headers: dict[str, str]
    cookies: dict[str, str]


class AvitoHttpClient:
    """
    Асинхронный HTTP-клиент для Avito на базе curl-cffi:
    - Имитация реального TLS-отпечатка браузера Chrome (JA3/JA4, HTTP/2)
    - Автоматическое слияние и сохранение обновлённых Set-Cookie
    - Поддержка HTTP/HTTPS/SOCKS5 прокси
    - Детектирование 429 / 439 и капчи
    """

    def __init__(
        self,
        cookies: Optional[dict[str, str]] = None,
        proxy_url: Optional[str] = None,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        impersonate: str = "chrome131",
        on_cookies_updated: Optional[Callable[[dict[str, str]], Awaitable[None]]] = None,
    ):
        self.cookies: dict[str, str] = dict(cookies or {})
        self.proxy_url = proxy_url or ""
        self.user_agent = user_agent
        self.impersonate = impersonate
        self.on_cookies_updated = on_cookies_updated
        self._lock = asyncio.Lock()

    def update_credentials(
        self,
        cookies: Optional[dict[str, str]] = None,
        proxy_url: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        if cookies is not None:
            self.cookies = dict(cookies)
        if proxy_url is not None:
            self.proxy_url = proxy_url
        if user_agent is not None:
            self.user_agent = user_agent

    def _default_headers(self, extra_headers: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": self.user_agent,
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _get_impersonate_order(self) -> list[str]:
        ordered = [self.impersonate] if self.impersonate else []
        for candidate in IMPERSONATE_CANDIDATES:
            if candidate not in ordered:
                ordered.append(candidate)
        return ordered

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        json_data: Optional[dict[str, Any]] = None,
        data: Optional[Any] = None,
        timeout: int = 25,
        check_antibot: bool = True,
    ) -> HttpResponseData:
        proxies = build_curl_proxies(self.proxy_url) if self.proxy_url else None
        merged_headers = self._default_headers(headers)

        last_exc: Optional[Exception] = None
        resp = None

        async with self._lock:
            for imp in self._get_impersonate_order():
                try:
                    async with AsyncSession(
                        impersonate=imp,
                        proxies=proxies,
                        timeout=timeout,
                        allow_redirects=True,
                    ) as session:
                        resp = await session.request(
                            method=method.upper(),
                            url=url,
                            headers=merged_headers,
                            params=params,
                            json=json_data,
                            data=data,
                            cookies=self.cookies,
                        )
                        # Сохраняем свежие cookies из ответа
                        resp_cookies = dict(resp.cookies.items()) if hasattr(resp, "cookies") else {}
                        if resp_cookies:
                            changed = False
                            for k, v in resp_cookies.items():
                                if v and self.cookies.get(k) != v:
                                    self.cookies[k] = v
                                    changed = True
                            if changed and self.on_cookies_updated:
                                await self.on_cookies_updated(dict(self.cookies))
                        break
                except Exception as exc:
                    err_str = str(exc).lower()
                    if "impersonate" in err_str or "browser" in err_str:
                        last_exc = exc
                        continue
                    if "proxy" in err_str or "connect" in err_str or "timeout" in err_str or "ssl" in err_str:
                        raise AvitoProxyError(f"Ошибка сети/прокси ({mask_proxy(self.proxy_url)}): {exc}") from exc
                    raise AvitoProxyError(f"Сетевая ошибка при запросе к Avito: {exc}") from exc

        if resp is None:
            raise AvitoProxyError(f"Не удалось инициализировать TLS-сессию curl-cffi: {last_exc}")

        status = int(resp.status_code)
        body_text = resp.text or ""
        final_url = str(resp.url)
        resp_headers = {str(k).lower(): str(v) for k, v in resp.headers.items()}

        if check_antibot:
            if status in (429, 439):
                raise AvitoRateLimitError(
                    f"Avito вернул HTTP {status} (лимит запросов / антибот). Проверьте прокси и интервалы.",
                    status_code=status,
                )
            if status in (401, 403):
                raise AvitoAuthError(
                    f"Avito отклонил доступ (HTTP {status}). Обновите cookies аккаунта или смените IP прокси."
                )
            lower_sample = body_text[:4000].lower()
            if "доступ ограничен" in lower_sample or "проблема с ip" in lower_sample:
                raise AvitoRateLimitError(
                    "Avito показал заглушку «Доступ ограничен: проблема с IP». Требуется смена прокси.",
                    status_code=status,
                )
            if "/profile/login" in final_url.lower():
                raise AvitoAuthError("Сессия Avito истекла (редирект на страницу входа).")

        return HttpResponseData(
            status_code=status,
            text=body_text,
            url=final_url,
            headers=resp_headers,
            cookies=dict(self.cookies),
        )

    async def diagnose(self) -> dict[str, Any]:
        """Комплексная диагностика прокси, TLS-отпечатка и доступности Avito."""
        result: dict[str, Any] = {
            "proxy": mask_proxy(self.proxy_url),
            "ip": "Не определён",
            "ip_latency_ms": None,
            "avito_status": None,
            "avito_latency_ms": None,
            "avito_ok": False,
            "note": "",
        }

        # 1. Проверка внешнего IP
        t0 = time.perf_counter()
        try:
            ip_resp = await self.request(
                "GET",
                "https://api.ipify.org?format=json",
                timeout=15,
                check_antibot=False,
            )
            result["ip_latency_ms"] = int((time.perf_counter() - t0) * 1000)
            if ip_resp.status_code == 200:
                parsed = json.loads(ip_resp.text)
                result["ip"] = parsed.get("ip", "Неизвестно")
            else:
                result["ip"] = f"HTTP {ip_resp.status_code}"
        except Exception as exc:
            result["note"] = f"Ошибка проверки IP: {exc}"
            return result

        # 2. Проверка доступности главной страницы Avito
        t1 = time.perf_counter()
        try:
            avito_resp = await self.request(
                "GET",
                "https://www.avito.ru/",
                timeout=20,
                check_antibot=False,
            )
            result["avito_latency_ms"] = int((time.perf_counter() - t1) * 1000)
            result["avito_status"] = avito_resp.status_code
            lower_text = avito_resp.text[:4000].lower()

            if avito_resp.status_code == 200 and "доступ ограничен" not in lower_text:
                result["avito_ok"] = True
                result["note"] = "Соединение с Avito стабильное, антибот-блокировок не обнаружено."
            elif "доступ ограничен" in lower_text or avito_resp.status_code in (403, 429, 439):
                result["note"] = (
                    f"Обнаружена блокировка IP со стороны Avito (HTTP {avito_resp.status_code}). "
                    "Смените прокси на мобильный или резидентский РФ."
                )
            else:
                result["note"] = f"Нестандартный ответ Avito: HTTP {avito_resp.status_code}"
        except Exception as exc:
            result["note"] = f"Ошибка подключения к Avito: {exc}"

        return result

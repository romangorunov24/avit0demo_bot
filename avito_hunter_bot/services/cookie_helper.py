from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


AUTH_COOKIE_KEYS = {"sessid", "u", "auth", "ft"}


@dataclass(slots=True)
class ParsedCookies:
    cookies: dict[str, str]
    is_authenticated: bool
    has_session_id: bool
    count: int

    def to_json(self) -> str:
        return json.dumps(self.cookies, ensure_ascii=False)

    def summary(self) -> str:
        status = "Авторизован (найдены сессионные токены)" if self.is_authenticated else "Гостевой набор (нет sessid/u)"
        return f"Кук загружено: {self.count} шт. | Статус: {status}"


def parse_cookies_input(raw_text: str) -> ParsedCookies:
    """
    Разбирает cookies из любого распространённого формата:
    1) JSON-массив объектов (Cookie-Editor / EditThisCookie): [{"name": "...", "value": "..."}, ...]
    2) JSON-словарь: {"sessid": "...", "u": "..."}
    3) Raw HTTP header: "sessid=...; u=...; ft=..."
    4) Netscape cookies.txt (строки с табуляцией)
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Пустой ввод cookies.")

    text = raw_text.strip()
    if text.lower().startswith("cookie:"):
        text = text[7:].strip()

    cookies: dict[str, str] = {}

    # Попытка 1: JSON
    if text.startswith("[") or text.startswith("{"):
        try:
            loaded: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Ошибка разбора JSON cookies: {exc}") from exc

        if isinstance(loaded, list):
            for item in loaded:
                if not isinstance(item, dict):
                    continue
                domain = str(item.get("domain", "")).lower()
                if domain and "avito" not in domain:
                    continue
                name = str(item.get("name", "")).strip()
                value = str(item.get("value", "")).strip()
                if name:
                    cookies[name] = value
        elif isinstance(loaded, dict):
            for k, v in loaded.items():
                name = str(k).strip()
                if name and v is not None:
                    cookies[name] = str(v).strip()
        else:
            raise ValueError("Неподдерживаемая JSON-структура cookies.")

    # Попытка 2: Netscape format (tab-separated)
    elif "\t" in text and "\n" in text:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain = parts[0].lower()
                if "avito" not in domain:
                    continue
                name = parts[5].strip()
                value = parts[6].strip()
                if name:
                    cookies[name] = value

    # Попытка 3: Raw header string "key=val; key2=val2"
    else:
        for pair in text.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            name = name.strip()
            value = value.strip()
            if name:
                cookies[name] = value

    if not cookies:
        raise ValueError(
            "Не удалось извлечь ни одной cookie для avito.ru. "
            "Проверьте формат (JSON из Cookie-Editor или строка Cookie из DevTools)."
        )

    lower_keys = {k.lower() for k in cookies}
    has_session_id = "sessid" in lower_keys or "u" in lower_keys
    is_authenticated = bool(lower_keys & AUTH_COOKIE_KEYS) and has_session_id

    return ParsedCookies(
        cookies=cookies,
        is_authenticated=is_authenticated,
        has_session_id=has_session_id,
        count=len(cookies),
    )


def cookies_from_json(raw_json: str | None) -> dict[str, str]:
    if not raw_json:
        return {}
    try:
        data = json.loads(raw_json)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}

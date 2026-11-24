"""Фильтры объявлений: слова, память, тихие часы."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import settings


def has_stop_words(text: str, stop_words_raw: str | None) -> bool:
    if not stop_words_raw:
        return False
    low = text.lower()
    words = [w.strip().lower() for w in stop_words_raw.split(",") if w.strip()]
    return any(w in low for w in words)


def has_plus_words(text: str, plus_words_raw: str | None) -> bool:
    if not plus_words_raw:
        return True
    low = text.lower()
    words = [w.strip().lower() for w in plus_words_raw.split(",") if w.strip()]
    if not words:
        return True
    return any(w in low for w in words)


_MEM_RE = re.compile(r"(?<!\d)(\d{1,4})\s*(gb|гб|tb|тб|g|г|t|т)(?![a-zа-яё0-9])", re.IGNORECASE)


def found_capacities(text: str) -> set[int]:
    """Объёмы памяти из текста в ГБ: '128 ГБ' -> 128, '1 ТБ' -> 1024."""
    result: set[int] = set()
    for num, unit in _MEM_RE.findall(text or ""):
        value = int(num)
        if unit.lower() in ("tb", "тб", "t", "т"):
            value *= 1024
        elif value == 1000:
            value = 1024
        result.add(value)
    return result


def memory_ok(text: str, wanted: str | int | None) -> bool:
    """True, если объём памяти не задан или встречается в тексте. Если в тексте памяти нет вовсе, объявление не подходит."""
    if not wanted:
        return True
    try:
        need = int(wanted)
    except (TypeError, ValueError):
        return True
    return need in found_capacities(text)


def _now() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.TZ_NAME))
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now()


def is_quiet_time(quiet_hours: str | None, now: datetime | None = None) -> bool:
    if not quiet_hours or "-" not in quiet_hours:
        return False
    try:
        start_s, end_s = quiet_hours.strip().split("-", 1)
        sh, sm = map(int, start_s.split(":"))
        eh, em = map(int, end_s.split(":"))
        now = now or _now()
        cur_m = now.hour * 60 + now.minute
        start_m = sh * 60 + sm
        end_m = eh * 60 + em
        if start_m <= end_m:
            return start_m <= cur_m < end_m
        return cur_m >= start_m or cur_m < end_m
    except Exception:
        return False

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from database import db
from services import worker
from services.filters import found_capacities, has_plus_words, has_stop_words, is_quiet_time, memory_ok
from services.search_url import build_search_url, resolve_city, validate_avito_url
from services.secrets import decrypt, encrypt
from services.spintax import render_spintax


def run(coro):
    return asyncio.run(coro)


# ---------- фильтры ----------
@pytest.mark.parametrize("text,wanted,expected", [
    ("Apple iPhone 13 Pro Max, 128 ГБ, серый", "128", True),
    ("Apple iPhone 13 Pro Max, 128 ГБ, серый", "64", False),
    ("iPhone 13 pro max 64gb", "64", True),
    ("iPhone 13 pro max 64Гб как новый", "64", True),
    ("Samsung S23, 8/256 ГБ", "256", True),
    ("Samsung S23, 8/256 ГБ", "8", False),
    ("iPhone 15 Pro, 1 ТБ", "1024", True),
    ("iPhone 15 Pro, 1TB", "1024", True),
    ("iPhone 13 в хорошем состоянии", "64", False),
    ("iPhone 13", None, True),
    ("iPhone 164 ГБ", "64", False),
])
def test_memory_filter(text, wanted, expected):
    assert memory_ok(text, wanted) is expected


def test_words():
    assert has_plus_words("айфон 13 чек коробка", "чек, гарантия")
    assert not has_plus_words("айфон 13", "чек, гарантия")
    assert has_plus_words("что угодно", None)
    assert has_stop_words("Айфон разбит экран", "разбит, запчасти")
    assert not has_stop_words("Айфон идеал", "разбит, запчасти")


def test_quiet_hours_use_timezone():
    msk_night = datetime(2026, 11, 25, 2, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    msk_day = datetime(2026, 11, 25, 15, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    assert is_quiet_time("23:00-08:00", msk_night)
    assert not is_quiet_time("23:00-08:00", msk_day)
    assert is_quiet_time("13:00-16:00", msk_day)


# ---------- ссылки ----------
def test_url_validation():
    assert validate_avito_url("https://www.avito.ru/moskva/telefony?q=iphone")
    assert validate_avito_url("http://avito.ru/moskva").startswith("https://")
    assert validate_avito_url("https://evil.com/?avito.ru") is None
    assert validate_avito_url("https://avito.ru.evil.com/") is None
    assert validate_avito_url("https://user:pw@avito.ru/") is None
    assert validate_avito_url("http://127.0.0.1/avito.ru") is None
    assert validate_avito_url("javascript:alert(1)") is None
    assert validate_avito_url(None) is None


def test_build_url_and_city():
    url = build_search_url("kazan", "iPhone 13 Pro Max")
    assert url == "https://www.avito.ru/kazan/telefony?q=iPhone+13+Pro+Max&s=104"
    assert validate_avito_url(url)
    assert resolve_city("Москва") == "moskva"
    assert resolve_city("СПб") == "sankt-peterburg"
    assert resolve_city("Нижний Новгород") == "nizhniy_novgorod"
    assert resolve_city("Атлантида") is None
    assert "evil" not in build_search_url("moskva", "x&redirect=evil.com").split("?q=")[0]


# ---------- шаблоны ----------
def test_spintax():
    out = render_spintax("{Привет|Добрый день}! Цена {price} ₽, торг {price_bargain} ₽, {title}", "iPhone", 50000)
    assert out.startswith(("Привет", "Добрый день"))
    assert "50 000 ₽" in out and "45 000 ₽" in out and "iPhone" in out
    no_price = render_spintax("За {price_bargain} ₽ отдадите?", "x", None)
    assert "₽" not in no_price and "{" not in no_price


# ---------- шифрование ----------
def test_crypto_roundtrip():
    token = encrypt('{"sessid":"abc"}')
    assert token.startswith("enc:") and "sessid" not in token
    assert decrypt(token) == '{"sessid":"abc"}'
    assert decrypt("plain-old-value") == "plain-old-value"
    assert encrypt(token) == token


def test_db_encrypts_cookies_and_migrates_plaintext():
    async def go():
        await db.init_db()
        await db.update_user_field(7, "avito_cookies", '{"sessid":"secret"}')
        import aiosqlite
        async with aiosqlite.connect(db.DB_FILE) as conn:
            raw = (await (await conn.execute("SELECT avito_cookies FROM users WHERE user_id=7")).fetchone())[0]
            assert raw.startswith("enc:") and "secret" not in raw
            await conn.execute("INSERT OR IGNORE INTO users (user_id, avito_cookies) VALUES (8, '{\"sessid\":\"old\"}')")
            await conn.commit()
        await db.init_db()  # миграция
        async with aiosqlite.connect(db.DB_FILE) as conn:
            raw8 = (await (await conn.execute("SELECT avito_cookies FROM users WHERE user_id=8")).fetchone())[0]
        assert raw8.startswith("enc:")
        assert (await db.get_user_settings(7))["avito_cookies"] == '{"sessid":"secret"}'
        assert (await db.get_user_settings(8))["avito_cookies"] == '{"sessid":"old"}'
    run(go())


def test_search_ownership():
    async def go():
        await db.init_db()
        sid = await db.add_search(user_id=100, name="mine", url="https://www.avito.ru/x", city="moskva", memory="128")
        assert (await db.get_search_owned(sid, 100))["memory"] == "128"
        assert await db.get_search_owned(sid, 999) is None
        assert await db.delete_search(sid, 999) is False
        assert await db.get_search_by_id(sid) is not None
        assert await db.delete_search(sid, 100) is True
        assert await db.get_search_by_id(sid) is None
    run(go())


# ---------- воркер ----------
class FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, **kw):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(kw)

    async def send_photo(self, **kw):
        raise RuntimeError("no photo in tests")


def item(i, title, price=40000, desc=""):
    return {"id": str(i), "title": title, "url": f"https://www.avito.ru/items/{i}", "price": price, "description": desc,
            "location": "Москва", "image_url": None, "seller_id": f"s{i}", "seller_code": "private",
            "seller_type": "Частное лицо", "discount_pct": 0}


def setup_search(monkeypatch, items, **kw):
    async def fake_parse(url, search_name="", ignore_backoff=False):
        return items
    monkeypatch.setattr(worker, "parse_avito_search", fake_parse)

    async def prep():
        await db.init_db()
        await db.grant_user_access(500)
        sid = await db.add_search(user_id=500, name="t", url="https://www.avito.ru/moskva/telefony?q=iphone", **kw)
        await db.update_search_field(sid, "is_initialized", 1)
        return await db.get_search_by_id(sid)
    return run(prep())


def test_worker_memory_filter_and_seen(monkeypatch):
    items = [item(1, "Apple iPhone 13 Pro Max, 64 ГБ"), item(2, "Apple iPhone 13 Pro Max, 128 ГБ"), item(3, "Чехол для iPhone 13")]
    s = setup_search(monkeypatch, items, memory="64")
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 1
    assert len(bot.sent) == 1 and "64 ГБ" in bot.sent[0]["text"]
    assert run(worker.process_single_search(bot, s)) == 0  # повторно не присылает


def test_preview_does_not_consume_items(monkeypatch):
    s = setup_search(monkeypatch, [item(11, "iPhone 13, 64 ГБ")])
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s, force_preview=True)) == 1
    assert run(db.is_item_seen(s["id"], "11")) is False
    assert run(worker.process_single_search(bot, s)) == 1  # настоящий мониторинг всё ещё видит лот


def test_failed_delivery_is_retried(monkeypatch):
    s = setup_search(monkeypatch, [item(21, "iPhone 13, 64 ГБ")])
    assert run(worker.process_single_search(FakeBot(fail=True), s)) == 0
    assert run(db.is_item_seen(s["id"], "21")) is False
    good = FakeBot()
    assert run(worker.process_single_search(good, s)) == 1


def test_price_and_stop_words(monkeypatch):
    items = [item(31, "iPhone 13, 128 ГБ", price=5000), item(32, "iPhone 13, 128 ГБ разбит", price=30000), item(33, "iPhone 13, 128 ГБ", price=30000)]
    s = setup_search(monkeypatch, items, min_price=10000, max_price=50000, stop_words="разбит")
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 1


def test_one_bad_search_does_not_stop_loop(monkeypatch):
    calls = []

    async def fake_active():
        return [{"id": 1}, {"id": 2}, {"id": 3}]

    async def fake_process(bot, search, force_preview=False):
        calls.append(search["id"])
        if search["id"] == 1:
            raise RuntimeError("boom")
        return 0

    async def fake_sleep(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(worker.db, "get_active_searches", fake_active)
    monkeypatch.setattr(worker, "process_single_search", fake_process)
    real_sleep = asyncio.sleep
    state = {"n": 0}

    async def sleep(t):
        state["n"] += 1
        if state["n"] > 3:
            raise asyncio.CancelledError
        await real_sleep(0)
    monkeypatch.setattr(worker.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        run(worker.worker_loop(FakeBot()))
    assert calls[:3] == [1, 2, 3]


def test_send_limits_and_duplicates():
    async def go():
        await db.init_db()
        us = {"seller_cooldown_hours": 24, "max_replies_hour": 2, "max_replies_day": 30}
        assert await worker.check_send_allowed(900, "a1", "s1", us) is None
        await db.log_sent_message(900, "a1", "s1", "t", "m", "sent")
        assert "уже писали" in await worker.check_send_allowed(900, "a1", "s2", us)
        assert "продавцу" in await worker.check_send_allowed(900, "a2", "s1", us)
        await db.log_sent_message(900, "a3", "s3", "t", "m", "sent")
        assert "лимит" in await worker.check_send_allowed(900, "a4", "s4", us)
    run(go())

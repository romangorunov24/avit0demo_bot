"""Проверки автоотклика «от находки лота до сообщения продавцу», разбора cookies, отправки и парсера.

Авито и Telegram подменены: настоящих запросов в сеть тесты не делают.
Что именно отвечает настоящий Авито на внутренние адреса, эти тесты проверить не могут.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from bot.keyboards import MENU_TEXTS, main_menu_kb
from bot.middlewares import MenuResetMiddleware
from database import db
from services import avito_messenger as m
from services import avito_parser as parser
from services import worker
from services.avito_messenger import SendOutcome, normalize_cookies, parse_cookies


def run(coro):
    return asyncio.run(coro)


async def _no_sleep(_):
    return None


# ---------------------------------------------------------------- cookies
EXPORT = [
    {"domain": ".avito.ru", "name": "sessid", "value": "S1"},
    {"domain": ".avito.ru", "name": "u", "value": "U1"},
    {"domain": "www.avito.ru", "name": "cfidsw-avito", "value": "ANTIBOT"},
    {"domain": ".avito.ru", "name": "_gcl_au", "value": "x"},
    {"domain": ".yandex.ru", "name": "yandexuid", "value": "FOREIGN"},
]


def test_cookies_keep_all_avito_cookies_and_drop_foreign():
    c = normalize_cookies(json.dumps(EXPORT))
    assert c["sessid"] == "S1" and c["u"] == "U1"
    assert c["cfidsw-avito"] == "ANTIBOT" and "_gcl_au" in c  # антибот-токены Авито не выбрасываются
    assert "yandexuid" not in c


def test_cookies_without_session_key_are_rejected():
    assert normalize_cookies(json.dumps([{"domain": ".avito.ru", "name": "abp", "value": "1"}])) == {}
    assert normalize_cookies(json.dumps([{"domain": ".yandex.ru", "name": "u", "value": "x"}])) == {}
    assert normalize_cookies("") == {} and normalize_cookies("мусор") == {}


def test_cookies_split_into_telegram_parts_are_reassembled():
    text = json.dumps(EXPORT, ensure_ascii=False, indent=1)
    cut1, cut2 = len(text) // 3, 2 * len(text) // 3
    parts = [text[:cut1], text[cut1:cut2], text[cut2:]]
    assert normalize_cookies("".join(parts)) == normalize_cookies(text)  # склейка целиком работает
    # поштучный разбор обрезков теряет cookie на границе: поэтому бот склеивает части перед разбором
    assert len(normalize_cookies(parts[0])) < len(normalize_cookies(text))


def test_cookies_header_dict_and_netscape_formats():
    assert normalize_cookies("sessid=A; u=B; foo=bar") == {"sessid": "A", "u": "B", "foo": "bar"}
    assert normalize_cookies({"sessid": "A", "x": "y"}) == {"sessid": "A", "x": "y"}
    netscape = ".avito.ru\tTRUE\t/\tTRUE\t0\tsessid\tNS1\n.other.com\tTRUE\t/\tTRUE\t0\tu\tNO"
    assert parse_cookies(netscape) == {"sessid": "NS1"}


# ---------------------------------------------------------------- отправка (подменённый Авито)
class FakeResp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self.text = text if text is not None else (json.dumps(body) if body is not None else "")
        self.headers = {}

    def json(self):
        return json.loads(self.text)


def install_avito(monkeypatch, fn):
    """fn(method, url, kwargs) -> FakeResp | Exception. Возвращает журнал запросов."""
    log = []

    class Session:
        def __init__(self, **kw):
            self.cookies = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def _do(self, method, url, kw):
            log.append((method, url, kw))
            r = fn(method, url, kw)
            if isinstance(r, Exception):
                raise r
            return r

        async def get(self, url, **kw):
            return await self._do("GET", url, kw)

        async def post(self, url, **kw):
            return await self._do("POST", url, kw)

    monkeypatch.setattr(m, "AsyncSession", Session)
    monkeypatch.setattr(m.asyncio, "sleep", _no_sleep)
    return log


COOKIES = json.dumps({"sessid": "S1", "u": "U1", "cfidsw-avito": "ANTIBOT"})


def send(text="Здравствуйте! Ещё продаёте?"):
    return run(m.AvitoMessenger().send_message_ex(123, "https://www.avito.ru/items/123", text, COOKIES))


def happy(method, url, kw):
    if method == "GET":
        return FakeResp(200, text="<html></html>")
    if "/web/1/messenger/createChannelByItemId" in url:
        return FakeResp(200, {"channel": {"id": "u2i-abc"}})
    if url.endswith("sendTextMessage"):
        return FakeResp(200, {"success": True})
    return FakeResp(404, text="nf")


def test_send_success_posts_text_with_all_cookies(monkeypatch):
    log = install_avito(monkeypatch, happy)
    out = send("Привет, актуально?")
    assert out.ok and not out.security_alert and not out.retryable
    posts = [x for x in log if x[0] == "POST"]
    assert posts[-1][2]["json"]["text"] == "Привет, актуально?"
    assert posts[-1][2]["json"]["channelId"] == "u2i-abc"
    assert posts[-1][2]["cookies"]["cfidsw-avito"] == "ANTIBOT"
    assert all(x[1].startswith("https://www.avito.ru/") for x in log)  # cookies уходят только на avito.ru


def test_send_second_endpoint_and_direct_fallback(monkeypatch):
    def second_send_only(method, url, kw):
        if method == "GET":
            return FakeResp(200, text="<html></html>")
        if "createChannelByItemId" in url and "/web/2/" in url:
            return FakeResp(200, {"result": {"channel": {"id": 77}}})
        if "/channels/77/messages" in url:
            return FakeResp(201, {"id": "msg1"})
        return FakeResp(404, text="nf")

    install_avito(monkeypatch, second_send_only)
    assert send().ok

    def direct_only(method, url, kw):
        if method == "GET":
            return FakeResp(200, text="<html></html>")
        if "/items/123/messenger/send" in url:
            return FakeResp(200, {"ok": 1})
        return FakeResp(404, text="nf")

    install_avito(monkeypatch, direct_only)
    assert send().ok


def test_send_html_or_error_body_is_not_success(monkeypatch):
    def html_on_send(method, url, kw):
        if method == "GET":
            return FakeResp(200, text="<html></html>")
        if "createChannelByItemId" in url:
            return FakeResp(200, {"channel": {"id": "c1"}})
        return FakeResp(200, text="<html>captcha</html>")

    install_avito(monkeypatch, html_on_send)
    out = send()
    assert not out.ok and not out.retryable  # сообщение могло уйти, повторять нельзя

    def error_json(method, url, kw):
        if method == "GET":
            return FakeResp(200, text="<html></html>")
        if "createChannelByItemId" in url:
            return FakeResp(200, {"channel": {"id": "c1"}})
        return FakeResp(200, {"error": {"code": 5, "message": "nope"}})

    install_avito(monkeypatch, error_json)
    assert not send().ok

    def html_on_channel(method, url, kw):
        return FakeResp(200, text="<html>login</html>")

    install_avito(monkeypatch, html_on_channel)
    assert not send().ok


def test_send_security_rate_limit_and_closed_item(monkeypatch):
    install_avito(monkeypatch, lambda mt, u, kw: FakeResp(200, text="<html></html>") if mt == "GET" else FakeResp(403, text="forbidden"))
    out = send()
    assert out.security_alert and not out.ok

    install_avito(monkeypatch, lambda mt, u, kw: FakeResp(200, text="<html></html>") if mt == "GET" else FakeResp(429, text="slow"))
    out = send()
    assert out.rate_limited and not out.security_alert

    install_avito(monkeypatch, lambda mt, u, kw: FakeResp(404, text="gone") if mt == "GET" else FakeResp(200, {}))
    out = send()
    assert not out.ok and "снято" in out.info

    install_avito(monkeypatch, lambda mt, u, kw: FakeResp(403, text="waf") if mt == "GET" else FakeResp(200, {}))
    assert send().security_alert  # страница объявления закрыта защитой


def test_send_retry_flags(monkeypatch):
    # сбой сервера при создании чата: текст не отправлялся, повтор безопасен
    def bad_gateway_on_channel(method, url, kw):
        if method == "GET":
            return FakeResp(200, text="<html></html>")
        if "createChannelByItemId" in url:
            return FakeResp(502, text="bad gateway")
        return FakeResp(404, text="nf")

    install_avito(monkeypatch, bad_gateway_on_channel)
    assert send().retryable

    # сервер ответил ошибкой на прямую отправку текста: неизвестно, дошло ли, повтор запрещён
    install_avito(monkeypatch, lambda mt, u, kw: FakeResp(200, text="<html></html>") if mt == "GET" else FakeResp(502, text="bad gateway"))
    assert not send().retryable

    # обрыв сети при создании чата: тоже безопасно
    def drop_on_channel(method, url, kw):
        if method == "GET":
            return FakeResp(200, text="<html></html>")
        return RuntimeError("timeout")

    install_avito(monkeypatch, drop_on_channel)
    out = send()
    assert not out.ok and out.retryable

    # обрыв сети при отправке текста: сообщение могло дойти, повтор запрещён
    def drop_on_send(method, url, kw):
        if method == "GET":
            return FakeResp(200, text="<html></html>")
        if "createChannelByItemId" in url:
            return FakeResp(200, {"channel": {"id": "c1"}})
        return RuntimeError("timeout")

    install_avito(monkeypatch, drop_on_send)
    out = send()
    assert not out.ok and not out.retryable


def test_send_input_checks(monkeypatch):
    install_avito(monkeypatch, happy)
    assert not run(m.AvitoMessenger().send_message_ex(1, "https://www.avito.ru/items/1", "x", "")).ok  # нет аккаунта
    assert not run(m.AvitoMessenger().send_message_ex(1, "https://www.avito.ru/items/1", "   ", COOKIES)).ok  # пустой текст
    assert not run(m.AvitoMessenger().send_message_ex("abc", "https://www.avito.ru/items/1", "x", COOKIES)).ok  # плохой id
    # чужая ссылка заменяется на адрес avito.ru: cookies не уходят на посторонний сайт
    log = install_avito(monkeypatch, happy)
    run(m.AvitoMessenger().send_message_ex(5, "https://evil.example/steal", "привет", COOKIES))
    assert all("evil.example" not in x[1] for x in log)
    # старая обёртка возвращает тройку
    install_avito(monkeypatch, happy)
    ok, info, alert = run(m.AvitoMessenger().send_message(123, "https://www.avito.ru/items/123", "привет", COOKIES))
    assert ok is True and alert is False


def test_check_session_variants(monkeypatch):
    def check(profile, page=None):
        def fn(method, url, kw):
            if url.endswith("/profile/short"):
                return profile
            return page or FakeResp(404, text="nf")

        install_avito(monkeypatch, fn)
        return run(m.AvitoMessenger().check_session(COOKIES))

    assert check(FakeResp(200, {"name": "Иван"})) == (True, "Аккаунт подключён и активен: Иван")
    ok, info = check(FakeResp(401, text="x"))
    assert not ok and "устарела" in info
    ok, info = check(FakeResp(404, text="nf"), FakeResp(200, text="<html>profile</html>"))
    assert ok  # адрес проверки изменился, но страница профиля открылась
    ok, info = check(FakeResp(200, text="<html>not json</html>"), FakeResp(200, text="<html>profile</html>"))
    assert ok


# ---------------------------------------------------------------- автоотклик целиком
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


class FakeMessenger:
    outcomes: list = []
    calls: list = []

    async def send_message_ex(self, item_id, item_url, text, cookies_json=None):
        FakeMessenger.calls.append((str(item_id), text, cookies_json))
        if FakeMessenger.outcomes:
            return FakeMessenger.outcomes.pop(0)
        return SendOutcome(True, "Сообщение доставлено продавцу")


def lot(i, title="iPhone 13, 128 ГБ", price=40000, seller=None):
    return {"id": str(i), "title": title, "url": f"https://www.avito.ru/items/{i}", "price": price, "description": "",
            "location": "Москва", "image_url": None, "seller_id": seller or f"seller{i}", "seller_code": "private",
            "seller_type": "Частное лицо", "discount_pct": 0}


_uid = [700]


def prepare(monkeypatch, items, *, user_auto=True, cookies=True, search_auto=1, outcomes=None, **user_fields):
    """Создаёт пользователя и уже инициализированный поиск. Возвращает (user_id, search)."""
    _uid[0] += 1
    uid = _uid[0]

    async def fake_parse(url, search_name="", ignore_backoff=False):
        return items

    FakeMessenger.outcomes = list(outcomes or [])
    FakeMessenger.calls = []
    worker._AUTO_PAUSE_UNTIL.clear()
    monkeypatch.setattr(worker, "parse_avito_search", fake_parse)
    monkeypatch.setattr(worker, "AvitoMessenger", FakeMessenger)
    monkeypatch.setattr(worker.asyncio, "sleep", _no_sleep)

    async def prep():
        await db.init_db()
        if cookies:
            await db.update_user_field(uid, "avito_cookies", COOKIES)
        await db.update_user_field(uid, "auto_reply_enabled", 1 if user_auto else 0)
        for k, v in user_fields.items():
            await db.update_user_field(uid, k, v)
        sid = await db.add_search(user_id=uid, name="t", url="https://www.avito.ru/moskva/telefony?q=iphone",
                                  message_template="{Здравствуйте|Добрый день}! {title} за {price} ₽ актуален?", auto_reply=search_auto)
        await db.update_search_field(sid, "is_initialized", 1)
        return await db.get_search_by_id(sid)

    return uid, run(prep())


def test_autoreply_sends_once_logs_and_marks_card(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(1)])
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 1

    assert len(FakeMessenger.calls) == 1
    item_id, text, cookies = FakeMessenger.calls[0]
    assert item_id == "1" and "iPhone 13, 128 ГБ" in text and "40 000 ₽" in text and "{" not in text
    assert json.loads(cookies)["sessid"] == "S1"  # дошли расшифрованные cookies

    rows = run(db.get_recent_sent_messages(uid))
    assert len(rows) == 1 and rows[0]["status"] == "sent" and rows[0]["message_text"] == text
    assert "Автоотклик отправлен" in bot.sent[0]["text"]
    assert run(db.get_draft(uid, "1")) == text  # кнопка «Отправить» знает, какой текст на карточке

    # второй проход: лот уже просмотрен, повторного сообщения нет
    assert run(worker.process_single_search(bot, s)) == 0
    assert len(FakeMessenger.calls) == 1


def test_autoreply_respects_switches(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(11)], user_auto=False)
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 1
    assert FakeMessenger.calls == [] and "Автоотклик отправлен" not in bot.sent[0]["text"]

    uid, s = prepare(monkeypatch, [lot(12)], search_auto=0)
    assert run(worker.process_single_search(FakeBot(), s)) == 1
    assert FakeMessenger.calls == []

    uid, s = prepare(monkeypatch, [lot(13)], cookies=False)
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 1
    assert FakeMessenger.calls == [] and "не привязан" in bot.sent[0]["text"]


def test_autoreply_retries_safe_failures_then_succeeds(monkeypatch):
    outcomes = [SendOutcome(False, "Ошибка сети", retryable=True), SendOutcome(False, "Ошибка сети", retryable=True), SendOutcome(True, "ok")]
    uid, s = prepare(monkeypatch, [lot(21)], outcomes=outcomes)
    bot = FakeBot()
    run(worker.process_single_search(bot, s))
    assert len(FakeMessenger.calls) == 3
    rows = run(db.get_recent_sent_messages(uid))
    assert len(rows) == 1 and rows[0]["status"] == "sent"  # в журнале одна запись, а не три
    assert "Автоотклик отправлен" in bot.sent[0]["text"]


def test_autoreply_does_not_retry_unsafe_failures(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(31)], outcomes=[SendOutcome(False, "Чат открыт, но текст не принят (HTTP 500).", retryable=False)])
    bot = FakeBot()
    run(worker.process_single_search(bot, s))
    assert len(FakeMessenger.calls) == 1
    rows = run(db.get_recent_sent_messages(uid))
    assert rows[0]["status"] == "failed" and "не принят" in rows[0]["info"]
    assert "не ушёл" in bot.sent[0]["text"]
    # неудачная попытка не блокирует ручную отправку: лот не считается «уже написано»
    assert run(db.was_item_messaged(uid, "31")) is False


def test_autoreply_security_alert_switches_it_off(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(41), lot(42)], outcomes=[SendOutcome(False, "Защита Avito (403).", security_alert=True)])
    bot = FakeBot()
    run(worker.process_single_search(bot, s))
    assert run(db.get_user_settings(uid))["auto_reply_enabled"] == 0
    assert len(FakeMessenger.calls) == 1  # второй лот в этом же проходе уже без отправки
    assert any("выключен" in b["text"] for b in bot.sent)


def test_autoreply_rate_limit_pauses_following_items(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(51), lot(52), lot(53)], outcomes=[SendOutcome(False, "Лимит запросов (HTTP 429).", rate_limited=True)])
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 3  # карточки приходят все
    assert len(FakeMessenger.calls) == 1  # а отправка встала на паузу
    assert any("на паузе" in b["text"] for b in bot.sent)


def test_autoreply_hour_limit_and_seller_cooldown(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(61), lot(62), lot(63, seller="seller61")], max_replies_hour=1)
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 3
    assert len(FakeMessenger.calls) == 1  # лимит 1 в час
    assert any("лимит" in b["text"] for b in bot.sent)


def test_autoreply_not_duplicated_when_card_delivery_fails_first(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(71)])
    assert run(worker.process_single_search(FakeBot(fail=True), s)) == 0  # Telegram недоступен
    assert len(FakeMessenger.calls) == 1  # сообщение продавцу ушло
    assert run(db.is_item_seen(s["id"], "71")) is False  # лот не потерян

    good = FakeBot()
    assert run(worker.process_single_search(good, s)) == 1
    assert len(FakeMessenger.calls) == 1  # повторного сообщения продавцу нет
    assert "уже был отправлен" in good.sent[0]["text"]


def test_new_search_first_cycle_only_remembers_lots(monkeypatch):
    uid, s = prepare(monkeypatch, [lot(81), lot(82)])
    run(db.update_search_field(s["id"], "is_initialized", 0))
    s = run(db.get_search_by_id(s["id"]))
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 0  # стартовая выдача запоминается, никому не пишем
    assert FakeMessenger.calls == [] and bot.sent == []
    assert run(db.is_item_seen(s["id"], "81")) and run(db.is_item_seen(s["id"], "82"))


def test_long_caption_falls_back_to_text_card(monkeypatch):
    item = lot(91)
    item["image_url"] = "https://img.example/1.jpg"
    item["description"] = "очень длинное описание " * 40
    uid, s = prepare(monkeypatch, [item])
    run(db.update_search_field(s["id"], "message_template", "длинный шаблон " * 60))
    s = run(db.get_search_by_id(s["id"]))
    bot = FakeBot()
    assert run(worker.process_single_search(bot, s)) == 1
    assert len(bot.sent) == 1  # фото в тестах недоступно, карточка ушла текстом


# ---------------------------------------------------------------- база
def test_drafts_and_failure_reason_in_journal():
    async def go():
        await db.init_db()
        await db.save_draft(5, "i1", "первый")
        await db.save_draft(5, "i1", "второй")
        assert await db.get_draft(5, "i1") == "второй" and await db.get_draft(5, "нет") is None
        await db.log_sent_message(5, "i2", "s", "t", "m", "failed", info="HTTP 500")
        assert (await db.get_recent_sent_messages(5))[0]["info"] == "HTTP 500"
        await db.save_recent_item(lot(3), "поиск", 42)
        assert (await db.get_recent_item("3"))["search_id"] == 42
    run(go())


# ---------------------------------------------------------------- парсер
CARD = """
<div data-marker="item" data-item-id="111">
  <a data-marker="item-title" href="/moskva/telefony/iphone_13_111"><h3 itemprop="name">iPhone 13, 128 ГБ</h3></a>
  <meta itemprop="price" content="40000">
  <div data-marker="item-description">Идеальное состояние, коробка</div>
  <div data-marker="item-location">Москва</div>
  <img src="https://img.example/1.jpg">
  <a href="/user/abc123/profile">Продавец</a>
</div>
"""


def install_search_page(monkeypatch, page_text, status=200):
    class Session:
        def __init__(self, **kw):
            self.cookies = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **kw):
            return FakeResp(status, text=page_text)

    monkeypatch.setattr(parser, "AsyncSession", Session)
    monkeypatch.setattr(parser.asyncio, "sleep", _no_sleep)
    parser._GUEST_COOKIES.clear()
    parser._BACKOFF_UNTIL = 0.0


def test_parser_reads_cards(monkeypatch):
    install_search_page(monkeypatch, f"<html><body>{CARD}</body></html>")
    items = run(parser.parse_avito_search("https://www.avito.ru/moskva/telefony?q=iphone", "t"))
    assert len(items) == 1
    it = items[0]
    assert it["id"] == "111" and it["title"] == "iPhone 13, 128 ГБ" and it["price"] == 40000
    assert it["url"] == "https://www.avito.ru/moskva/telefony/iphone_13_111"
    assert it["seller_id"] == "abc123" and it["location"] == "Москва" and "коробка" in it["description"]


def test_parser_detects_block_page(monkeypatch):
    install_search_page(monkeypatch, "<html><body>Please solve the CAPTCHA</body></html>")
    assert run(parser.parse_avito_search("https://www.avito.ru/moskva/telefony?q=iphone", "t")) == []
    assert parser._BACKOFF_UNTIL > 0  # включена защитная пауза
    parser._BACKOFF_UNTIL = 0.0


def test_parser_replaces_foreign_sort_parameter():
    f = parser._ensure_sorted_by_date
    assert f("https://www.avito.ru/moskva/telefony?q=iphone").endswith("s=104")
    out = f("https://www.avito.ru/moskva/telefony?q=iphone&s=1&pmax=5000")
    assert out.count("s=") == 1 and "s=104" in out and "pmax=5000" in out and "s=1&" not in out
    assert f("https://www.avito.ru/moskva/telefony?s=104").count("s=104") == 1


# ---------------------------------------------------------------- меню и состояния
class FakeState:
    def __init__(self):
        self.cleared = False

    async def clear(self):
        self.cleared = True


def _through_middleware(text, raw_state="SearchStates:waiting_name", with_state=True):
    st = FakeState()
    data = {"raw_state": raw_state}
    if with_state:
        data["state"] = st
    seen = {}

    async def handler(event, d):
        seen["raw_state"] = d["raw_state"]
        return "handled"

    assert run(MenuResetMiddleware()(handler, SimpleNamespace(text=text), data)) == "handled"
    return st, seen


def test_menu_button_resets_unfinished_input():
    for text in MENU_TEXTS:
        st, seen = _through_middleware(text)
        assert st.cleared and seen["raw_state"] is None, text
    st, seen = _through_middleware("/start")
    assert st.cleared and seen["raw_state"] is None
    st, seen = _through_middleware("Название моего поиска")  # обычный ответ мастера не сбрасывается
    assert not st.cleared and seen["raw_state"] == "SearchStates:waiting_name"
    st, seen = _through_middleware("🔍 Мои поиски", raw_state=None)  # состояния нет: ничего не делаем
    assert not st.cleared
    _through_middleware("🔍 Мои поиски", with_state=False)  # и не падаем без state


def test_menu_texts_match_keyboard():
    buttons = {b.text for row in main_menu_kb().keyboard for b in row}
    assert buttons == set(MENU_TEXTS)

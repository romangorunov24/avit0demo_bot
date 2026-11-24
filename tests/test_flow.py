"""Сквозные проверки обработчиков Telegram без сети: поддельная сессия записывает вызовы Bot API."""
import asyncio
from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.handlers import actions, searches, settings as settings_handler, start
from bot.middlewares import AccessMiddleware
from database import db


class RecSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText", "EditMessageCaption"):
            return Message(message_id=len(self.calls), date=datetime.now(), chat=Chat(id=1, type="private"))
        return True

    async def stream_content(self, *a, **k):
        yield b""

    def texts(self):
        return [getattr(c, "text", None) or getattr(c, "caption", None) or getattr(c, "text", "") for c in self.calls]


def user(uid):
    return User(id=uid, is_bot=False, first_name=f"u{uid}")


def msg(uid, text=None):
    return Message(message_id=1, date=datetime.now(), chat=Chat(id=uid, type="private"), from_user=user(uid), text=text)


class Harness:
    def __init__(self):
        self.session = RecSession()
        self.bot = Bot("123456:TEST", session=self.session)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp.message.middleware(AccessMiddleware())
        self.dp.callback_query.middleware(AccessMiddleware())
        for r in (start.router, searches.router, settings_handler.router, actions.router):
            self.dp.include_router(r)
        self.n = 0

    async def say(self, uid, text):
        self.n += 1
        await self.dp.feed_update(self.bot, Update(update_id=self.n, message=msg(uid, text)))

    async def tap(self, uid, data):
        self.n += 1
        cq = CallbackQuery(id=str(self.n), from_user=user(uid), chat_instance="x", data=data, message=msg(uid, "card"))
        await self.dp.feed_update(self.bot, Update(update_id=self.n, callback_query=cq))


@pytest.fixture(scope="module")
def h():
    asyncio.run(db.init_db())
    return Harness()


def test_param_wizard_creates_search_with_city_and_memory(h):
    async def go():
        await h.say(1, "🧭 Поиск по параметрам")
        await h.tap(1, "city:kazan")
        await h.say(1, "iPhone 13 Pro Max")
        await h.tap(1, "mem:64")
        for step in ("skip_min_price", "skip_max_price", "skip_sniper_price", "skip_plus_words", "skip_stop_words"):
            await h.tap(1, step)
        found = await db.get_user_searches(1)
        assert len(found) == 1
        s = found[0]
        assert s["city"] == "kazan" and s["memory"] == "64"
        assert s["url"] == "https://www.avito.ru/kazan/telefony?q=iPhone+13+Pro+Max&s=104"
        assert "Казань" in s["name"] and "64" in s["name"]
    asyncio.run(go())


def test_other_user_cannot_touch_foreign_search(h):
    async def go():
        sid = (await db.get_user_searches(1))[0]["id"]
        await db.grant_user_access(2)
        for data in (f"sview_{sid}", f"stoggle_{sid}", f"sauto_{sid}", f"srun_{sid}", f"sedit_price_{sid}", f"sdel_{sid}"):
            await h.tap(2, data)
        s = await db.get_search_by_id(sid)
        assert s is not None and s["is_active"] == 1 and s["auto_reply"] == 1
    asyncio.run(go())


def test_fake_url_rejected(h):
    async def go():
        await h.say(1, "➕ Добавить поиск")
        await h.say(1, "тест")
        before = len(h.session.calls)
        await h.say(1, "https://evil.example/?avito.ru")
        sent = [getattr(c, "text", "") for c in h.session.calls[before:]]
        assert any("корректная ссылка" in (t or "") for t in sent)
        await h.tap(1, "cancel_fsm")
    asyncio.run(go())


def test_unknown_user_is_ignored_and_admin_commands_are_admin_only(h):
    async def go():
        before = len(h.session.calls)
        await h.say(555, "/start")
        await h.say(555, "/grant 555")
        assert len(h.session.calls) == before
        assert await db.is_user_allowed(555) is False
        await h.say(2, "/grant 777")  # пользователь с доступом, но не админ
        assert await db.is_user_allowed(777) is False
        await h.say(1, "/grant 777")  # админ
        assert await db.is_user_allowed(777) is True
    asyncio.run(go())


def test_disconnect_account_no_longer_crashes(h):
    async def go():
        await db.update_user_field(1, "avito_cookies", '{"sessid":"x","u":"y"}')
        await db.update_user_field(1, "auto_reply_enabled", 1)
        await h.tap(1, "acc_disconnect")
        u = await db.get_user_settings(1)
        assert u["avito_cookies"] is None and u["auto_reply_enabled"] == 0
    asyncio.run(go())

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddSearchStates(StatesGroup):
    waiting_name = State()
    waiting_url_or_query = State()
    waiting_region = State()
    waiting_price_range = State()
    waiting_keywords = State()
    waiting_template = State()


class EditSearchTemplateStates(StatesGroup):
    waiting_template = State()


class AccountStates(StatesGroup):
    waiting_cookies = State()
    waiting_proxy = State()


class AutoReplySettingsStates(StatesGroup):
    waiting_default_template = State()
    waiting_limits = State()
    waiting_scan_interval = State()

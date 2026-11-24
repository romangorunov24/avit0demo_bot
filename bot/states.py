from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_min_price = State()
    waiting_max_price = State()
    waiting_template = State()


class AccountStates(StatesGroup):
    waiting_cookies_pc = State()
    waiting_mobile_session = State()
    waiting_default_template = State()


class ActionStates(StatesGroup):
    waiting_custom_message = State()
    waiting_custom_reply = State()

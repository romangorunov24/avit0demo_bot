from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_min_price = State()
    waiting_max_price = State()
    waiting_sniper_price = State()
    waiting_stop_words = State()
    waiting_plus_words = State()


class AccountStates(StatesGroup):
    waiting_cookies = State()
    waiting_spintax = State()
    waiting_hourly_limit = State()


class ActionStates(StatesGroup):
    waiting_custom_message = State()

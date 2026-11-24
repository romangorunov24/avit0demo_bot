from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    waiting_name = State()
    waiting_url = State()
    waiting_min_price = State()
    waiting_max_price = State()
    waiting_sniper_price = State()
    waiting_plus_words = State()
    waiting_stop_words = State()
    waiting_edit_field = State()


class SettingsStates(StatesGroup):
    waiting_tpl_main = State()
    waiting_tpl_bargain = State()
    waiting_tpl_delivery = State()
    waiting_quiet_hours = State()
    waiting_discount_pct = State()
    waiting_cookies = State()
    waiting_ab_limits = State()
    waiting_ab_delay = State()
    waiting_ab_cooldown = State()
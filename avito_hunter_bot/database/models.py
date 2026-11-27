from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class SearchTask:
    id: int
    name: str
    search_url: str
    query: str = ""
    region: str = "rossiya"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    include_words: str = ""
    exclude_words: str = ""
    reply_template: str = ""
    auto_reply: bool = True
    is_active: bool = True
    initialized: bool = False
    created_at: str = ""
    last_checked_at: Optional[str] = None


@dataclass(slots=True)
class AvitoItem:
    item_id: str
    title: str
    price: int
    price_text: str
    url: str
    city: str = ""
    seller_id: str = ""
    seller_name: str = ""
    description: str = ""
    image_url: str = ""
    is_promoted: bool = False
    published_text: str = ""


@dataclass(slots=True)
class ReplyLog:
    id: int
    item_id: str
    seller_id: str
    channel_id: str
    message_text: str
    status: str
    error_message: str = ""
    created_at: str = ""


@dataclass(slots=True)
class BotSettings:
    avito_cookies_json: str = "{}"
    guest_cookies_json: str = "{}"
    proxy_url: str = ""
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    auto_reply_enabled: bool = False
    default_template: str = (
        "Здравствуйте! Заинтересовало ваше объявление «{title}». "
        "Подскажите, пожалуйста, оно ещё актуально?"
    )
    hourly_limit: int = 12
    daily_limit: int = 60
    reply_delay_min: int = 8
    reply_delay_max: int = 22
    dedup_seller_days: int = 7
    scan_interval_sec: int = 45
    account_user_id: str = ""
    account_name: str = ""

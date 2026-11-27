from __future__ import annotations

import os
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str = Field(..., min_length=10, description="Telegram Bot API Token")
    ADMIN_IDS: str = Field(default="", description="Comma-separated Telegram user IDs")
    DATABASE_PATH: str = Field(default="data/avito_bot.db")
    DEFAULT_PROXY: str = Field(default="")
    IMPERSONATE_BROWSER: str = Field(default="chrome131")
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: str = Field(default="logs/bot.log")

    @property
    def admin_id_list(self) -> list[int]:
        result: list[int] = []
        for raw in self.ADMIN_IDS.split(","):
            cleaned = raw.strip()
            if cleaned.isdigit():
                result.append(int(cleaned))
        return result


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    db_dir = os.path.dirname(settings.DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    return settings

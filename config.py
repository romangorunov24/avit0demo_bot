from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: str = ""
    PROXY_URL: str | None = None
    CHECK_INTERVAL_SEC: int = 90
    DB_PATH: str = "data/avito_bot.db"
    TZ_NAME: str = "Europe/Moscow"
    COOKIES_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("BOT_TOKEN", "DB_PATH", mode="before")
    @classmethod
    def _strip_required(cls, v: object) -> str:
        return str(v).strip()

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def _strip_admins(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("PROXY_URL", mode="before")
    @classmethod
    def _strip_optional(cls, v: object) -> str | None:
        if v is None:
            return None
        cleaned = str(v).strip()
        return cleaned if cleaned else None

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip().isdigit() and int(x.strip()) > 0]


settings = Settings()
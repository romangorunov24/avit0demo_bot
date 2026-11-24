from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: str
    PROXY_URL: str | None = None
    CHECK_INTERVAL_SEC: int = 5
    DB_PATH: str = "avito_bot.db"
    AVITO_USER_ID: str | None = None
    AVITO_ACCESS_TOKEN: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(x.strip()) for x in str(self.ADMIN_IDS).split(",") if x.strip().isdigit()]


settings = Settings()

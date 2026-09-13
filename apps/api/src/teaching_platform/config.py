from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = ""
    redis_url: str = ""
    session_secret: str = ""
    ph8_base_url: str = "https://ph8.co/v1"
    ph8_model: str = "deepseek-v4-flash"
    ph8_api_key: str = ""
    file_storage_root: str = "./var/files"
    worker_poll_interval_seconds: float = 2.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_api_settings(settings: Settings) -> None:
    if len(settings.session_secret) < 32:
        raise RuntimeError(
            "SESSION_SECRET is required and must contain at least 32 characters. "
            "Copy .env.template and set a local secret before starting the API."
        )


def validate_worker_settings(settings: Settings) -> None:
    validate_api_settings(settings)
    if not settings.ph8_api_key:
        raise RuntimeError(
            "PH8_API_KEY is required for the worker and must be provided only in the "
            "server environment."
        )


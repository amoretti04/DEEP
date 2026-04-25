"""API settings. Environment-driven, no hardcoded secrets."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    dip_env: str = "local"
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://dip:dip_local_only@localhost:5432/dip"
    )
    api_host: str = "0.0.0.0"  # noqa: S104 — bind-all is fine in the local container
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:5173"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

"""Application configuration, loaded from the environment."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Async SQLAlchemy DSN (asyncpg driver).
    database_url: str = "postgresql+asyncpg://sensor:sensor@localhost:5432/sensorstream"
    log_level: str = "INFO"

    # Static API key gating the mutating endpoints (ingest/patch/delete). When
    # unset, write auth is DISABLED (a startup warning is logged) so local dev
    # and tests stay frictionless; set it to require an X-API-Key header.
    api_key: str | None = None

    # Cap batch ingest size so a single request can't exhaust memory / a txn.
    max_batch_size: int = 10_000
    # Default + max page sizes for list endpoints.
    default_page_size: int = 50
    max_page_size: int = 500

    @property
    def asyncpg_dsn(self) -> str:
        """Plain asyncpg DSN (no SQLAlchemy driver prefix) for COPY/seed."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()

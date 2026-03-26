"""
Project Argus — Application configuration loaded from environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql://argus:argus_local@localhost:5432/argus"

    # NAZK API
    nazk_api_base_url: str = "https://public-api.nazk.gov.ua/v2"
    nazk_concurrency: int = 3
    nazk_retry_attempts: int = 3
    nazk_page_delay_seconds: float = 0.3
    nazk_timeout_seconds: float = 30.0

    # Data storage
    raw_data_dir: str = "data/raw"


settings = Settings()

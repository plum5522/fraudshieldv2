"""All settings come from environment variables, so the same code runs locally,
in CI and on Azure with different values and no secrets in the repo."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # SQLite file locally; on Azure this is set to the Postgres URL.
    database_url: str = "sqlite:///./fraudshield.db"
    # Secret key for hashing reporter IDs. MUST be overridden in production.
    reporter_secret: str = "dev-only-change-me"
    # Reports older than this stop counting (scam numbers get abandoned and recycled).
    report_window_days: int = 30


settings = Settings()

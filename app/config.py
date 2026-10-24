"""All settings come from environment variables, so the same code runs locally,
in CI and on Azure with different values and no secrets in the repo."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # SQLite file locally; on Azure this is set to the Postgres URL.
    database_url: str = "sqlite:///./fraudshield.db"
    # Secret key for hashing reporter IDs. MUST be overridden in production.
    reporter_secret: str = "dev-only-change-me"  # = DEV_SECRET below
    # Reports older than this stop counting (scam numbers get abandoned and recycled).
    report_window_days: int = 30
    # Report rate limits per rolling hour. Per reporter stops one device spamming; per IP
    # makes it harder to fake many reporters from one machine (not impossible: VPNs).
    reports_per_reporter_per_hour: int = 10
    reports_per_ip_per_hour: int = 30


DEV_SECRET = "dev-only-change-me"


def check_production_safety(s: Settings) -> None:
    """Fail fast: a real database with the public dev secret would let anyone who reads
    this repo reverse reporter hashes. Better to refuse to start than run insecurely."""
    if not s.database_url.startswith("sqlite") and s.reporter_secret == DEV_SECRET:
        raise RuntimeError("REPORTER_SECRET must be set when using a real database.")


settings = Settings()

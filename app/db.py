"""Database tables and session handling (SQLAlchemy ORM).

Each class below is one table; each attribute is one column. The ORM turns Python
objects into SQL, uses bound parameters (so no SQL injection), and lets the same code
run on SQLite (tests) and PostgreSQL (production).

All timestamps are stored in UTC.
"""

from datetime import datetime

from sqlalchemy import (DateTime, ForeignKey, Index, Integer, String, UniqueConstraint,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class EntityRecord(Base):
    """One row per distinct identifier ever reported (a UPI ID, phone, domain or short link)."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(512))
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)

    # The same identifier must never appear twice, or its reports would split.
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_entity_kind_value"),)


class ReportRecord(Base):
    """One row per (identifier, person) report. No message text is stored: privacy by design."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    reporter_hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256 hex, never the raw ID
    category: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    __table_args__ = (
        # Anti-poisoning: one person counts once per identifier, enforced by the database
        # itself, so no application bug or race condition can break it.
        UniqueConstraint("entity_id", "reporter_hash", name="uq_report_entity_reporter"),
        # Speeds up "reports for this entity in the last 30 days".
        Index("ix_reports_entity_created", "entity_id", "created_at"),
    )


def make_engine(url: str):
    # SQLite blocks use from other threads by default; FastAPI serves requests on a thread pool.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=engine) -> None:
    """Create tables if missing. (A real migration tool, Alembic, is the next step.)"""
    Base.metadata.create_all(bind)


def get_session():
    """FastAPI dependency: one session per request, always closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

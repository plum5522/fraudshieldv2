"""Repository layer: every database query lives here, nowhere else.

The routes never write SQL, and this module never deals with HTTP, so each side can be
tested and changed on its own.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.config import settings
from app.db import EntityRecord, ReportRecord
from app.extract import Entity


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _insert(session: Session, table):
    """INSERT that supports ON CONFLICT DO NOTHING on both Postgres and SQLite."""
    dialect = postgresql if session.get_bind().dialect.name == "postgresql" else sqlite
    return dialect.insert(table)


def record_report(session: Session, entities: list[Entity], reporter_hash: str,
                  category: str, now: datetime | None = None) -> dict[str, bool]:
    """Store one report per entity. Returns {entity_key: True if new, False if this
    person had already reported it}.

    Both inserts use ON CONFLICT DO NOTHING instead of "check, then insert". Check-then-
    insert has a race: two requests both see "not there" and both insert. Letting the
    UNIQUE constraint decide is atomic, so it stays correct under concurrent requests.
    """
    now = now or utcnow()
    result: dict[str, bool] = {}
    for ent in entities:
        # 1. Get-or-create the entity row.
        session.execute(
            _insert(session, EntityRecord)
            .values(kind=ent.kind, value=ent.value, first_seen=now, last_seen=now)
            .on_conflict_do_nothing(index_elements=["kind", "value"])
        )
        entity_id = session.scalar(
            select(EntityRecord.id).where(EntityRecord.kind == ent.kind, EntityRecord.value == ent.value)
        )
        # 2. Insert the report; a repeat report by the same person is silently ignored.
        # RETURNING gives back the new id, or no row at all on conflict. (rowcount is not
        # reliable for ON CONFLICT across drivers: it broke on Postgres in testing.)
        new_id = session.scalar(
            _insert(session, ReportRecord)
            .values(entity_id=entity_id, reporter_hash=reporter_hash, category=category, created_at=now)
            .on_conflict_do_nothing(index_elements=["entity_id", "reporter_hash"])
            .returning(ReportRecord.id)
        )
        inserted = new_id is not None
        if inserted:
            session.execute(update(EntityRecord).where(EntityRecord.id == entity_id).values(last_seen=now))
        result[ent.key] = inserted
    session.commit()
    return result


def reporter_counts(session: Session, entities: list[Entity], now: datetime | None = None) -> dict[str, int]:
    """Distinct people who reported each entity within the window, in ONE query.

    COUNT(*) equals COUNT(DISTINCT reporter) here because the UNIQUE constraint already
    guarantees one row per person per entity. Counting on read (instead of keeping a
    report_count column) can never drift out of sync.
    """
    if not entities:
        return {}
    since = (now or utcnow()) - timedelta(days=settings.report_window_days)
    rows = session.execute(
        select(EntityRecord.kind, EntityRecord.value, func.count(ReportRecord.id))
        .join(ReportRecord, ReportRecord.entity_id == EntityRecord.id)
        .where(tuple_(EntityRecord.kind, EntityRecord.value).in_([(e.kind, e.value) for e in entities]))
        .where(ReportRecord.created_at >= since)
        .group_by(EntityRecord.kind, EntityRecord.value)
    ).all()
    counts = {f"{kind}:{value}": n for kind, value, n in rows}
    return {e.key: counts.get(e.key, 0) for e in entities}


def entity_history(session: Session, entity: Entity, now: datetime | None = None) -> dict | None:
    """Everything known about one identifier, or None if it was never reported."""
    record = session.scalar(
        select(EntityRecord).where(EntityRecord.kind == entity.kind, EntityRecord.value == entity.value)
    )
    if record is None:
        return None
    since = (now or utcnow()) - timedelta(days=settings.report_window_days)
    by_category = dict(session.execute(
        select(ReportRecord.category, func.count())
        .where(ReportRecord.entity_id == record.id)
        .group_by(ReportRecord.category)
    ).all())
    recent = session.scalar(
        select(func.count()).where(ReportRecord.entity_id == record.id, ReportRecord.created_at >= since)
    )
    return {
        "kind": record.kind,
        "value": record.value,
        "first_seen": record.first_seen,
        "last_seen": record.last_seen,
        "reporters_total": sum(by_category.values()),
        "reporters_recent": recent,
        "window_days": settings.report_window_days,
        "categories": by_category,
    }

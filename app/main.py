"""HTTP layer only: parse the request, call the services, shape the response.
No SQL and no business rules live here."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from app import reports
from app.db import get_session, init_db
from app.extract import clean_message, extract_entities
from app.models import (CheckedEntity, CheckRequest, CheckResponse, EntityHistory, EntityOut,
                        ReportRequest, ReportResponse)
from app.trust import hash_reporter, is_trusted


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="FraudShield v2", version="2.0.0", lifespan=lifespan)


def _out(e) -> EntityOut:
    return EntityOut(kind=e.kind, value=e.value)


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.post("/v1/check", response_model=CheckResponse)
def check(req: CheckRequest, session: Session = Depends(get_session)) -> CheckResponse:
    """Network half of the verdict for now; the text model and fusion are added next."""
    entities = extract_entities(clean_message(req.message))
    untrusted = [e for e in entities if not is_trusted(e)]
    counts = reports.reporter_counts(session, untrusted)
    return CheckResponse(entities=[
        CheckedEntity(kind=e.kind, value=e.value, trusted=is_trusted(e),
                      reporters_recent=counts.get(e.key, 0))
        for e in entities
    ])


@app.post("/v1/reports", response_model=ReportResponse, status_code=201)
def create_report(req: ReportRequest, session: Session = Depends(get_session)) -> ReportResponse:
    entities = extract_entities(clean_message(req.message))
    trusted = [e for e in entities if is_trusted(e)]
    reportable = [e for e in entities if not is_trusted(e)]
    if not reportable:
        raise HTTPException(422, "No reportable UPI ID, phone number or link found in the message.")

    outcome = reports.record_report(session, reportable, hash_reporter(req.reporter_id), req.category)
    return ReportResponse(
        recorded=[_out(e) for e in reportable if outcome[e.key]],
        duplicates=[_out(e) for e in reportable if not outcome[e.key]],
        ignored=[_out(e) for e in trusted],
    )


@app.get("/v1/entities", response_model=EntityHistory)
def get_entity(q: str = Query(min_length=3, max_length=512, description="A UPI ID, phone number or link, in any format"),
               session: Session = Depends(get_session)) -> EntityHistory:
    """Lookup by raw value: the same extractor normalises it, so clients can pass
    '+91 98765-43210' or '9876543210' and hit the same record."""
    found = extract_entities(q)
    if not found:
        raise HTTPException(422, "No UPI ID, phone number or link found in q.")
    history = reports.entity_history(session, found[0])
    if history is None:
        raise HTTPException(404, "No reports for this identifier.")
    return EntityHistory(**history)

"""HTTP layer only: parse the request, call the services, shape the response.
No SQL and no business rules live here."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app import reports
from app.classifier import TextClassifier, get_classifier
from app.config import settings
from app.db import get_session, init_db
from app.extract import clean_message, extract_entities
from app.fusion import fuse
from app.models import (CheckedEntity, CheckRequest, CheckResponse, EntityHistory, EntityOut,
                        ReportRequest, ReportResponse)
from app.ratelimit import SlidingWindowLimiter
from app.trust import hash_reporter, is_trusted

HOUR = 3600


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_classifier()  # load the model at startup, not on the first user's request
    # Created per app start, stored on app.state (each test client gets fresh limiters).
    app.state.reporter_limiter = SlidingWindowLimiter(settings.reports_per_reporter_per_hour, HOUR)
    app.state.ip_limiter = SlidingWindowLimiter(settings.reports_per_ip_per_hour, HOUR)
    yield


def enforce_report_limits(request: Request, reporter_hash: str) -> None:
    """Raise 429 Too Many Requests with a Retry-After header if either limit is hit.
    Runs before any database work, so a flood never reaches Postgres."""
    # Behind Azure's proxy, request.client.host is the client only if uvicorn runs with
    # --proxy-headers (it then trusts X-Forwarded-For). See the Dockerfile.
    ip = request.client.host if request.client else "unknown"
    for limiter, key in ((request.app.state.ip_limiter, f"ip:{ip}"),
                         (request.app.state.reporter_limiter, f"reporter:{reporter_hash}")):
        allowed, retry_after = limiter.check(key)
        if not allowed:
            raise HTTPException(429, "Too many reports. Try again later.",
                                headers={"Retry-After": str(retry_after)})


app = FastAPI(title="FraudShield v2", version="2.0.0", lifespan=lifespan)


def _out(e) -> EntityOut:
    return EntityOut(kind=e.kind, value=e.value)


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "version": app.version, "model_version": get_classifier().version}


@app.post("/v1/check", response_model=CheckResponse)
def check(req: CheckRequest, session: Session = Depends(get_session),
          classifier: TextClassifier = Depends(get_classifier)) -> CheckResponse:
    """Fused verdict: what the text says + what people have reported."""
    entities = extract_entities(clean_message(req.message))
    untrusted = [e for e in entities if not is_trusted(e)]
    counts = reports.reporter_counts(session, untrusted)

    text_p = classifier.scam_probability(req.message)
    top = max(untrusted, key=lambda e: counts[e.key], default=None)
    reporters = counts[top.key] if top else 0
    v = fuse(text_p, reporters)

    return CheckResponse(
        verdict=v.tier, probability=v.probability, text_probability=v.text_probability,
        reporters=reporters, reasons=_reasons(v, top, entities),
        entities=[CheckedEntity(kind=e.kind, value=e.value, trusted=is_trusted(e),
                                reporters_recent=counts.get(e.key, 0)) for e in entities],
        model_version=classifier.version,
    )


def _reasons(v, top, entities) -> list[str]:
    reasons = []
    if v.text_probability >= 0.7:
        reasons.append(f"The wording matches known scam messages ({v.text_probability:.0%}).")
    elif v.text_probability >= 0.3:
        reasons.append(f"The wording looks somewhat like scam messages ({v.text_probability:.0%}).")
    else:
        reasons.append("The wording looks like a normal message.")
    if top and v.reporters:
        people = "person" if v.reporters == 1 else "people"
        reasons.append(f"{top.value} was reported by {v.reporters} {people} in the last "
                       f"{settings.report_window_days} days.")
    trusted = [e.value for e in entities if is_trusted(e)]
    if trusted:
        reasons.append(f"Links to an official site: {', '.join(trusted)}.")
    return reasons


@app.post("/v1/reports", response_model=ReportResponse, status_code=201)
def create_report(req: ReportRequest, request: Request,
                  session: Session = Depends(get_session)) -> ReportResponse:
    reporter_hash = hash_reporter(req.reporter_id)
    enforce_report_limits(request, reporter_hash)

    entities = extract_entities(clean_message(req.message))
    trusted = [e for e in entities if is_trusted(e)]
    reportable = [e for e in entities if not is_trusted(e)]
    if not reportable:
        raise HTTPException(422, "No reportable UPI ID, phone number or link found in the message.")

    outcome = reports.record_report(session, reportable, reporter_hash, req.category)
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

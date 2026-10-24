# FraudShield v2

A scam-message checking API for India that judges a message on two signals at once:
**what the text says** (a trained classifier) and **what other people have reported**
about the UPI IDs, phone numbers and links inside it. One user's report protects the
next user, even when the scammer rewords the message.

> Work in progress. Built solo as a clean rebuild of
> [FraudShield India](https://github.com/fraudshield-india/fraudshield-backend),
> a hackathon project I built with Pranav Achanta and Aditya.

## Status

| Part | State |
|---|---|
| Entity extraction (UPI, phone, links, short links) + carrier-tag stripping + masking | Done |
| Reports database: anti-poisoning, 30-day window, race-free inserts | Done |
| Rate limiting on reports (sliding window, per reporter and per IP) | Done |
| Text classifier (TF-IDF + logistic regression) and fused verdict | Planned |
| CI, Docker, Azure deploy | Planned |

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/health` | Liveness |
| POST | `/v1/check` | Identifiers in a message and how many people reported each |
| POST | `/v1/reports` | Report a scam message (each person counts once per identifier) |
| GET | `/v1/entities?q=...` | History of one UPI ID, phone number or link, in any format |

Interactive docs at `/docs` when running.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs
```

## Tests

```bash
pytest                                   # SQLite, fast
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/fraudshield_test pytest   # real Postgres
```

## Design decisions

- **Identifiers are extracted with regex, not an LLM.** One wrong character would link two unrelated scams.
- **`UNIQUE(entity_id, reporter_hash)`**: one person counts once per identifier, enforced by the database.
- **`INSERT ... ON CONFLICT DO NOTHING RETURNING id`** instead of check-then-insert, which races under concurrent requests (see `tests/test_concurrency.py`).
- **Counts are computed on read**, not stored in a counter column that could drift.
- **No message text is stored**, only identifiers. Reporter IDs are stored as HMAC-SHA256 with a server secret.
- **Sliding-window rate limits** on reports (10/hour per reporter, 30/hour per IP), checked before any database work. In-memory, so single-instance only; Redis is the multi-instance answer.
- **Trusted domains** (gov.in, banks, major platforms) can never collect reports.
- **Carrier labels like "Airtel Warning: SPAM |" are stripped** before anything reads the text, to avoid training-data leakage.

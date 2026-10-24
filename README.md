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
| Text classifier (TF-IDF + logistic regression) and fused verdict | Done |
| CI, Docker, Azure deploy | Planned |

## How the verdict works

```
logit(final) = logit(p_text) + 1.0 * ln(1 + reporters_last_30_days)
```

| Text model | Reporters | Final | Verdict |
|---|---|---|---|
| 60% | 5 | ~90% | confirmed_scam |
| 60% | 0 (new scammer) | 60% | suspicious |
| 5% (normal message) | 5 (fake reports) | ~24% | safe |

The text alone can never produce `confirmed_scam`; that needs at least 3 reporters.
Reports alone can't convict a clearly normal message.

## The model, honestly

TF-IDF (word 1-2 grams + character 2-5 grams) feeding logistic regression, trained in about 8 seconds
on 3,722 messages from two public, LLM-generated datasets (credited below). UPI IDs, phones and
links are masked to `<UPI>`, `<PHONE>`, `<URL>` (or `<SAFE_URL>` for official sites) so the model
learns scam *wording*, while the database learns scammer *identities*.

| Evaluation | AUC | False positives | Recall |
|---|---|---|---|
| Unseen templates, same datasets (grouped split) | 0.997 | 2.3% | 98% |
| Trained without dataset A, tested on A (hard negatives) | 0.92 | 37% | 96% |
| Trained without dataset B, tested on B | 0.96 | 1.8% | 75% |
| 9 real, documented scam SMS | | | 8 of 9 |

The first row is the flattering one. The second is the honest warning: on legit messages written
differently from its training data (official bank notices), the model raises far more false alarms.
No public dataset of real Indian scam SMS exists, so the fix is collecting real legitimate messages,
which is the next data task. Full numbers: `models/metrics.json`. Retrain: `python -m ml.train`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/health` | Liveness |
| POST | `/v1/check` | Fused verdict (safe / suspicious / likely_scam / confirmed_scam) with plain-language reasons |
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
- **Train/test split by template**, not by row: the synthetic data reuses templates with different names and numbers, so a random split would test memorisation.
- **One `prepare_for_model()` function** is used by both training and the API, so they can't drift apart (training/serving skew).
- **Carrier labels like "Airtel Warning: SPAM |" are stripped** before anything reads the text, to avoid training-data leakage.

## Data credits

- [indian-scam-sms-synthetic-audited](https://huggingface.co/datasets/Ridham115/indian-scam-sms-synthetic-audited), CC BY 4.0
- [scam_ham_india_14_languages](https://huggingface.co/datasets/anmolshrivastav/scam_ham_india_14_languages), MIT (English, Hinglish and Hindi subset used)
- `data/real/real_scams.csv`: scam SMS received by the author, plus texts quoted in the linked news reports

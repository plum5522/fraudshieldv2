"""End-to-end tests through HTTP, against a fresh in-memory database each time."""

SCAM = "Your KYC is blocked. Pay Rs 10 to refund.desk@ybl or call +91 98765 43210"


def report(client, reporter, message=SCAM, category="kyc_freeze"):
    return client.post("/v1/reports", json={"message": message, "reporter_id": reporter, "category": category})


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


# ---------- /v1/reports ----------

def test_report_records_each_identifier(client):
    r = report(client, "rohan-device-01")
    assert r.status_code == 201
    assert r.json()["recorded"] == [
        {"kind": "upi", "value": "refund.desk@ybl"},
        {"kind": "phone", "value": "+919876543210"},
    ]


def test_repeat_report_is_a_duplicate(client):
    report(client, "rohan-device-01")
    r = report(client, "rohan-device-01")
    assert r.json()["recorded"] == [] and len(r.json()["duplicates"]) == 2


def test_trusted_domain_never_recorded(client):
    r = report(client, "rohan-device-01", "Scam! pay pay.now@ybl. Complain at cybercrime.gov.in")
    assert r.status_code == 201
    assert r.json()["ignored"] == [{"kind": "domain", "value": "cybercrime.gov.in"}]
    assert r.json()["recorded"] == [{"kind": "upi", "value": "pay.now@ybl"}]


def test_message_with_only_trusted_link_rejected(client):
    r = report(client, "rohan-device-01", "Visit https://echallan.parivahan.gov.in to pay")
    assert r.status_code == 422


def test_message_without_identifiers_rejected(client):
    assert report(client, "rohan-device-01", "You won a lottery!!").status_code == 422


def test_bad_category_rejected(client):
    assert report(client, "rohan-device-01", category="made_up").status_code == 422


def test_short_reporter_id_rejected(client):
    assert report(client, "abc").status_code == 422


# ---------- /v1/check ----------

def test_check_shows_report_counts(client):
    for person in ["rohan-device-01", "meera-device-02", "kabir-device-03"]:
        report(client, person)
    # Different wording, same UPI ID, different phone format
    r = client.post("/v1/check", json={"message": "Refund ready! accept request from REFUND.DESK@ybl"})
    assert r.json()["entities"] == [
        {"kind": "upi", "value": "refund.desk@ybl", "reporters_recent": 3, "trusted": False}
    ]


def test_check_strips_carrier_tag_and_marks_trusted(client):
    r = client.post("/v1/check", json={"message": "Airtel Warning: SPAM | pay at https://echallan.parivahan.gov.in"})
    assert r.json()["entities"] == [
        {"kind": "domain", "value": "echallan.parivahan.gov.in", "reporters_recent": 0, "trusted": True}
    ]


def test_empty_and_oversized_messages_rejected(client):
    assert client.post("/v1/check", json={"message": ""}).status_code == 422
    assert client.post("/v1/check", json={"message": "a" * 4001}).status_code == 422


# ---------- /v1/entities ----------

def test_entity_lookup_any_phone_format(client):
    report(client, "rohan-device-01")
    for q in ["9876543210", "+91-98765-43210"]:
        r = client.get("/v1/entities", params={"q": q})
        assert r.status_code == 200, q
        assert r.json()["value"] == "+919876543210"
        assert r.json()["reporters_recent"] == 1


def test_entity_lookup_unknown_is_404(client):
    assert client.get("/v1/entities", params={"q": "nobody@ybl"}).status_code == 404


def test_entity_lookup_garbage_is_422(client):
    assert client.get("/v1/entities", params={"q": "hello there"}).status_code == 422


# ---------- Rate limiting on /v1/reports ----------

def test_reporter_rate_limit(client):
    # Default: 10 reports per reporter per hour. Different messages, same person.
    for i in range(10):
        assert report(client, "spammy-device-01", f"Pay to scam{i:02d}@ybl now").status_code == 201
    r = report(client, "spammy-device-01", "Pay to scam99@ybl now")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    # The refused report never reached the database
    assert client.get("/v1/entities", params={"q": "scam99@ybl"}).status_code == 404


def test_ip_rate_limit_stops_fake_reporters(client):
    # Default: 30 per IP per hour, even if every request claims a different reporter.
    codes = [report(client, f"fake-reporter-{i:03d}").status_code for i in range(31)]
    assert codes[:30] == [201] * 30
    assert codes[30] == 429


def test_check_is_not_rate_limited(client):
    for _ in range(40):
        assert client.post("/v1/check", json={"message": "pay to refund.desk@ybl"}).status_code == 200


# ---------- Fused verdict on /v1/check ----------

import pytest  # noqa: E402

from app.classifier import get_classifier  # noqa: E402
from app.main import app  # noqa: E402


class FakeClassifier:
    """Fixed text score, so these tests check OUR logic, not the model's opinion."""
    version = "fake-1"

    def __init__(self, p):
        self.p = p

    def scam_probability(self, message):
        return self.p


@pytest.fixture
def text_score():
    def set_score(p):
        app.dependency_overrides[get_classifier] = lambda: FakeClassifier(p)
    yield set_score
    app.dependency_overrides.pop(get_classifier, None)


def check(client, message):
    return client.post("/v1/check", json={"message": message}).json()


def test_unsure_text_with_many_reports_is_confirmed(client, text_score):
    text_score(0.60)
    for i in range(5):
        report(client, f"witness-{i:02d}-device")
    r = check(client, "Hi, refund ready, accept request from refund.desk@ybl")
    assert r["verdict"] == "confirmed_scam"
    assert r["reporters"] == 5 and r["probability"] == pytest.approx(0.90, abs=0.01)
    assert any("reported by 5 people" in s for s in r["reasons"])


def test_new_scammer_caught_by_text_alone(client, text_score):
    text_score(0.60)
    r = check(client, "Hi, refund ready, accept request from brand.new@ybl")
    assert r["verdict"] == "suspicious" and r["reporters"] == 0


def test_fake_reports_cannot_convict_normal_message(client, text_score):
    for i in range(5):
        report(client, f"troll-{i:02d}-device", "Report this shop: honest.kirana@ybl")
    text_score(0.05)
    r = check(client, "Thanks for shopping! Paid Rs 240 to honest.kirana@ybl")
    assert r["verdict"] in ("safe", "suspicious") and r["probability"] < 0.3


def test_trusted_link_mentioned_in_reasons(client, text_score):
    text_score(0.02)
    r = check(client, "Your challan status is at https://echallan.parivahan.gov.in")
    assert r["verdict"] == "safe"
    assert any("official site" in s for s in r["reasons"])


def test_real_model_end_to_end(client):
    """The real trained model, through the full story from the README."""
    monday = "Your KYC is pending. Account will be blocked today. Pay Rs 10 to verify at refund.desk@ybl"
    first = check(client, monday)
    assert first["text_probability"] > 0.5 and first["model_version"].startswith("tfidf-lr")
    for i in range(5):
        report(client, f"user-{i:02d}-device", monday)
    friday = "Dear customer, complete re-verification by paying Rs 1 to refund.desk@ybl"
    later = check(client, friday)
    assert later["reporters"] == 5
    assert later["probability"] > later["text_probability"]
    assert later["verdict"] in ("likely_scam", "confirmed_scam")

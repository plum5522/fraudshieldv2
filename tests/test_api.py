from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_classify_returns_entities():
    r = client.post("/v1/classify", json={"message": "Pay to refund@ybl or call 9876543210"})
    assert r.status_code == 200
    assert r.json()["entities"] == [
        {"kind": "upi", "value": "refund@ybl"},
        {"kind": "phone", "value": "+919876543210"},
    ]


def test_empty_message_rejected():
    assert client.post("/v1/classify", json={"message": ""}).status_code == 422


def test_oversized_message_rejected():
    assert client.post("/v1/classify", json={"message": "a" * 4001}).status_code == 422

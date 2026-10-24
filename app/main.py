"""HTTP layer only: parse the request, call the services, shape the response.
No business logic lives here, so every piece can be unit-tested without HTTP."""

from fastapi import FastAPI

from app.extract import extract_entities
from app.models import ClassifyRequest, ClassifyResponse, EntityOut

app = FastAPI(title="FraudShield v2", version="2.0.0")


@app.get("/v1/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.post("/v1/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest) -> ClassifyResponse:
    entities = extract_entities(req.message)
    return ClassifyResponse(entities=[EntityOut(kind=e.kind, value=e.value) for e in entities])

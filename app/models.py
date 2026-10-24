"""Request and response shapes. Pydantic validates every request at the edge,
so the rest of the code can trust its inputs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# An SMS is ~160 chars, a long WhatsApp forward a few thousand. Without a cap, one huge
# request could tie up the server.
Message = Field(min_length=1, max_length=4000)

Category = Literal[
    "phishing_link", "traffic_challan", "parcel_delivery", "reward_points", "kyc_freeze",
    "digital_arrest", "job_scam", "lottery", "loan_scam", "other",
]


class EntityOut(BaseModel):
    kind: str
    value: str


class CheckRequest(BaseModel):
    message: str = Message


class CheckedEntity(EntityOut):
    reporters_recent: int
    trusted: bool


class CheckResponse(BaseModel):
    verdict: Literal["safe", "suspicious", "likely_scam", "confirmed_scam"]
    probability: float        # fused: text + reports
    text_probability: float   # the classifier alone
    reporters: int            # people who reported the most-reported identifier (30 days)
    reasons: list[str]        # plain-language explanation for the user
    entities: list[CheckedEntity]
    model_version: str


class ReportRequest(BaseModel):
    message: str = Message
    # Device or account ID from the client app. Only its HMAC is stored.
    reporter_id: str = Field(min_length=8, max_length=128)
    category: Category = "other"


class ReportResponse(BaseModel):
    recorded: list[EntityOut]     # new reports
    duplicates: list[EntityOut]   # this person had already reported these
    ignored: list[EntityOut]      # trusted identifiers, never counted


class EntityHistory(BaseModel):
    kind: str
    value: str
    first_seen: datetime
    last_seen: datetime
    reporters_total: int
    reporters_recent: int
    window_days: int
    categories: dict[str, int]

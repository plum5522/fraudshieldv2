"""Request and response shapes. Pydantic validates every request at the edge,
so the rest of the code can trust its inputs."""

from pydantic import BaseModel, Field


class ClassifyRequest(BaseModel):
    # Cap the size: an SMS is ~160 chars, a long WhatsApp forward a few thousand.
    # Without a cap, one huge request could tie up the LLM and run up cost.
    message: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="api", max_length=32)


class EntityOut(BaseModel):
    kind: str
    value: str


class ClassifyResponse(BaseModel):
    entities: list[EntityOut]

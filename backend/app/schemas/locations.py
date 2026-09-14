"""``GET /locations/resolve`` (contract v0.2 §3.4). Always one of three
outcomes; an empty answer on its own is forbidden (AC1.1.4)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ReferencePointOut


class MatchedOut(BaseModel):
    label: str
    kind: Literal["suburb", "postcode", "point"]


class SuggestionOut(BaseModel):
    label: str
    kind: Literal["suburb", "postcode"]
    code: str | None = None


class CoverageOut(BaseModel):
    description: str
    examples: list[str] = Field(default_factory=list)


class ResolveOut(BaseModel):
    outcome: Literal["resolved", "outside_coverage", "unresolved"]
    query: str
    reference_point: ReferencePointOut | None = None
    matched: MatchedOut | None = None
    message: str | None = None
    coverage: CoverageOut | None = None
    suggestions: list[SuggestionOut] = Field(default_factory=list)

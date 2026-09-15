"""``GET /sources`` (contract v0.2 §3.5) - the register behind the Sources and
licences page required by constraint C2."""

from typing import Literal

from pydantic import BaseModel, Field

SourceStatus = Literal["loaded", "empty", "failed_using_last_good", "not_used"]


class SourceOut(BaseModel):
    id: str
    name: str
    publisher: str | None = None
    licence: str | None = None
    licence_url: str | None = None
    attribution: str | None = None
    url: str | None = None
    tier: str | None = None
    publisher_scope: str | None = None
    publisher_last_updated: str | None = None
    retrieved_at: str | None = None
    stale_after_days: int
    possibly_out_of_date: bool
    feeds: list[str] = Field(default_factory=list)
    status: SourceStatus
    row_count: int | None = None
    mode: Literal["live", "sample"] | None = None
    note: str | None = None


class SourcesOut(BaseModel):
    sources: list[SourceOut]

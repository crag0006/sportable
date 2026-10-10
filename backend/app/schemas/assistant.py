"""``POST /api/v1/assistant`` request and response (contract v0.3 section 8).

The response carries what the chat panel renders: the answer text, the cards,
the links the server built, the sources, the "what I checked" trace and, after
a calendar action, the calendar proposal. Nothing in it was written by the
model except ``answer`` and ``suggested_questions``.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["answer", "results", "clarify", "no_information", "capability", "unavailable"]
Page = Literal["search", "venue", "directions", "events", "event", "saved", "home"]


class ContextIn(BaseModel):
    """What the page already knows (section 8.2)."""

    page: Page | None = None
    venue_id: str | None = None
    event_id: str | None = None
    location: str | None = None
    distance_m: int | None = None
    recent_event_ids: list[str] = Field(default_factory=list, max_length=20)


class TurnIn(BaseModel):
    """One earlier turn, text only."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AssistantRequest(BaseModel):
    """The body of ``POST /api/v1/assistant``."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "question": "Basketball near Preston with an accessible toilet?",
                    "context": {"page": "search", "location": "Preston", "distance_m": 500},
                    "history": [],
                }
            ]
        }
    )

    question: str = Field(min_length=1, max_length=500)
    context: ContextIn | None = None
    history: list[TurnIn] = Field(default_factory=list, max_length=6)


class LinkOut(BaseModel):
    """A button: ready-made label, server-built href."""

    kind: Literal[
        "venue",
        "event",
        "search",
        "directions",
        "registration",
        "publisher",
        "google_template",
        "ics",
    ]
    label: str
    href: str


class SourceChipOut(BaseModel):
    """A dataset a fact in this turn came from."""

    name: str
    publisher_last_updated: str | None = None
    attribution: str | None = None


class PassageOut(BaseModel):
    """A passage of a program description the answer drew on."""

    program_id: str
    title: str | None = None
    quote: str
    href: str
    source: str


class TraceStepOut(BaseModel):
    """One entry of "what I checked", written by the server."""

    step: int
    tool: str
    summary: str
    href: str | None = None
    passages: list[PassageOut] = Field(default_factory=list)


class CalendarItemOut(BaseModel):
    """One event the user chose for a calendar, with its links."""

    event_id: str
    title: str
    when: str
    # The event's ``calendar`` block (section 7.7) as the events API returns it.
    calendar: dict[str, Any] | None = None
    links: list[LinkOut] = Field(default_factory=list)


class NotExportableOut(BaseModel):
    """A chosen event the decision table excludes, with the sentence to show."""

    event_id: str
    title: str
    message: str


class CalendarProposalOut(BaseModel):
    """The calendar block of a response (section 8.10)."""

    items: list[CalendarItemOut] = Field(default_factory=list)
    download_all: LinkOut | None = None
    not_exportable: list[NotExportableOut] = Field(default_factory=list)


class ResultsOut(BaseModel):
    """Compact cards for the ids the model named, only ids a tool returned this turn."""

    venues: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


class AssistantResponse(BaseModel):
    """The response of ``POST /api/v1/assistant`` (section 8.3)."""

    kind: Kind
    answer: str
    results: ResultsOut = Field(default_factory=ResultsOut)
    links: list[LinkOut] = Field(default_factory=list)
    sources: list[SourceChipOut] = Field(default_factory=list)
    trace: list[TraceStepOut] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    calendar_proposal: CalendarProposalOut | None = None
    notice: str = "This conversation is not stored."
    model_called: bool
    partial: bool = False

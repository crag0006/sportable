"""Response models for the events endpoints (contract v0.2 section 7).

Two kinds of row share one shape: a dated ``fixture`` (``starts_at``) and a
recurring ``program`` (``recurrence``). Every event carries the four facility
tiles of its venue, or four "no published information" tiles when the venue
could not be matched, so an event and its venue page can never disagree.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import FacilityOut, ReferencePointOut, SourceRefOut
from app.schemas.venues import CorridorOut, VenueCardOut

Kind = Literal["fixture", "program"]


class RecurrenceOut(BaseModel):
    """Programs only. ``days_stated`` is false when the publisher gave no weekday."""

    weekdays: list[str] = Field(default_factory=list)
    time_of_day: list[str] = Field(default_factory=list)
    days_stated: bool
    summary: str


class EventVenueOut(BaseModel):
    matched: bool
    match_basis: str
    venue_id: str | None = None
    name: str | None = None
    address: str | None = None
    suburb: str | None = None
    postcode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    href: str | None = None
    message: str | None = None


class EventAccessOut(BaseModel):
    facilities: list[FacilityOut]
    requested_met: bool | None = None
    group: Literal["matched", "undocumented", "not_available"] | None = None
    summary: str


class EventLinksOut(BaseModel):
    detail: str
    venue: str | None = None
    directions: str | None = None
    ics: str
    external: str
    registration: str | None = None


class EventSourceOut(SourceRefOut):
    attribution: str | None = None


class EventOut(BaseModel):
    id: str
    kind: Kind
    title: str
    sport: str | None = None
    sport_raw: str | None = None
    competition: str | None = None
    season: str | None = None
    grade: str | None = None
    round: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    organisation: str | None = None
    description: str | None = None
    status: str
    status_label: str
    starts_at: str | None = None
    ends_at: str | None = None
    date_local: str | None = None
    time_local: str | None = None
    timezone: str
    recurrence: RecurrenceOut | None = None
    price: str | None = None
    age_ranges: list[str] = Field(default_factory=list)
    access_needs: list[str] = Field(default_factory=list)
    venue: EventVenueOut
    distance_m: int | None = None
    access: EventAccessOut
    links: EventLinksOut
    source: EventSourceOut


class WindowOut(BaseModel):
    from_: str = Field(alias="from")
    to: str
    timezone: str
    rule: str

    model_config = {"populate_by_name": True}


class EventFiltersOut(BaseModel):
    sport: list[str] = Field(default_factory=list)
    status: str
    facilities_requested: list[str] = Field(default_factory=list)
    distance_limit_m: int
    within_m: int | None = None
    venue_id: str | None = None
    weekday: list[str] = Field(default_factory=list)
    time_of_day: list[str] = Field(default_factory=list)
    price: str | None = None


class EventCountsOut(BaseModel):
    total: int
    fixtures: int
    programs: int
    by_date: dict[str, int]
    unmatched_venue: int
    matched: int | None = None
    undocumented: int | None = None
    not_available: int | None = None


class EventGroupOut(BaseModel):
    label: str
    count: int
    events: list[EventOut]


class EventListOut(BaseModel):
    window: WindowOut
    filters: EventFiltersOut
    reference_point: ReferencePointOut | None = None
    counts: EventCountsOut
    page: int
    page_size: int
    events: list[EventOut]
    undocumented_group: EventGroupOut | None = None
    not_available_group: EventGroupOut | None = None
    attribution: list[str] = Field(default_factory=list)
    empty_message: str | None = None


class EventSportOut(BaseModel):
    name: str
    event_count: int


class EventSportsOut(BaseModel):
    window: WindowOut
    sports: list[EventSportOut]


class ShareOut(BaseModel):
    url: str


class EventDetailOut(EventOut):
    venue_card: VenueCardOut | None = None
    share: ShareOut
    # US3.3 - Read Aloud, one complete sentence per element (AC3.3.3). On the
    # detail model rather than on EventOut because AC3.3.1 is about a page's
    # important information, and a list of fifty rows would otherwise carry
    # fifty summaries nothing ever speaks.
    summary_sentences: list[str] = Field(default_factory=list)


# ------------------------------------------------------- directions (US4.2)
# AC4.2.4 asks "Get Directions" to show the route to the EVENT and the
# accessible facilities along it. That is the venue requirement pointed at a
# different target, so the payload is the venue corridor object unchanged,
# wrapped in the two things an event adds: which event this is, and whether a
# route exists for it at all.
RouteUnavailableReason = Literal["venue_not_matched"]


class RoutingProviderOut(BaseModel):
    """What was, or was not, asked of the routing provider (DS-05).

    Stated in the payload rather than left implicit because DS-05 is a
    request-time service with a quota, the events page multiplies the number of
    times a directions view is opened, and "why is this a straight line" is a
    question the answer to should travel with the answer.
    """

    provider: str
    # ``not_used`` is the normal state: no request was made, so no quota was
    # spent and nothing can fail. ``degraded`` is reserved for the day a routed
    # leg is added and the provider is unavailable — the page still renders the
    # corridor rather than erroring.
    status: Literal["not_used", "degraded"]
    note: str


class DirectionsEventOut(BaseModel):
    """Just enough of the event to caption the map. The full record is /events/{id}."""

    id: str
    kind: Kind
    title: str
    status: str
    status_label: str
    starts_at: str | None = None
    date_local: str | None = None
    time_local: str | None = None
    timezone: str
    recurrence_summary: str | None = None
    href: str


class EventDirectionsOut(BaseModel):
    event: DirectionsEventOut
    # False when the event's venue could not be matched to a DS-01 venue. The
    # corridor is then null and ``message`` says why: an empty facility list
    # would read as "we checked and there is nothing on the way", which is a
    # different and untrue statement.
    route_available: bool
    reason: RouteUnavailableReason | None = None
    message: str
    corridor: CorridorOut | None = None
    routing: RoutingProviderOut

"""Events (contract v0.2 section 7): list and calendar, sports, detail, calendar file."""

from datetime import date, timedelta

from fastapi import APIRouter, Request, Response

from app.api.deps import Events, NowDep, SettingsDep
from app.api.params import first_of, parse_band, parse_facilities, place_input
from app.api.queries import (
    DateFromQ,
    DateToQ,
    DistanceQ,
    FacilitiesQ,
    IdsQ,
    IncludePastQ,
    NearQ,
    OptionalOriginQ,
    PageQ,
    PageSizeQ,
    PostcodeQ,
    PriceQ,
    SportsQ,
    StatusQ,
    SuburbQ,
    TimeOfDayQ,
    TypesQ,
    VenueIdQ,
    WeekdayQ,
    WithinMQ,
    WithinQ,
)
from app.api.v1.routes.venues import corridor_query
from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.events import WEEKDAYS
from app.domain.facilities import KEY_TO_KIND
from app.schemas.events import EventDetailOut, EventDirectionsOut, EventListOut, EventSportsOut
from app.services.inputs import EventListQuery

router = APIRouter()

MAX_WITHIN_M = 50_000
MAX_PAGE_SIZE = 200
MAX_IDS = 50


def _ids(request: Request) -> tuple[str, ...]:
    """``ids=a,b,c`` as a tuple in request order, at most MAX_IDS, de-duplicated."""
    seen: list[str] = []
    for value in _csv(request, "ids"):
        if value not in seen:
            seen.append(value)
    if len(seen) > MAX_IDS:
        raise ApiError(422, "validation_error", f"ids: at most {MAX_IDS} ids per request")
    return tuple(seen)


def _parse_date(raw: str | None, name: str) -> date | None:
    """``YYYY-MM-DD`` or None; anything else is a 422 naming the parameter."""
    if raw is None or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ApiError(422, "validation_error", f"{name}: expected YYYY-MM-DD") from exc


def _window(request: Request, settings: Settings, today: date) -> tuple[date, date]:
    """The inclusive date window, defaulted and bounded by ``/config``."""
    ev = settings.events
    date_from = _parse_date(request.query_params.get("from"), "from") or today
    date_to = _parse_date(request.query_params.get("to"), "to") or (
        date_from + timedelta(days=ev.default_window_days)
    )
    if date_to < date_from:
        raise ApiError(422, "invalid_date_range", "to must not be before from")
    if (date_to - date_from).days > ev.max_window_days:
        raise ApiError(
            422,
            "invalid_date_range",
            f"the window must be at most {ev.max_window_days} days",
        )
    return date_from, date_to


def _csv(request: Request, name: str) -> tuple[str, ...]:
    """A comma list, possibly repeated, as a tuple of trimmed values."""
    out: list[str] = []
    for raw in request.query_params.getlist(name):
        out.extend(v.strip() for v in raw.split(",") if v.strip())
    return tuple(out)


def _int(raw: str | None, name: str, default: int, lo: int, hi: int) -> int:
    """An integer within ``lo..hi``, or the default when absent; else a 422."""
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiError(422, "validation_error", f"{name}: expected an integer") from exc
    if not (lo <= value <= hi):
        raise ApiError(422, "validation_error", f"{name}: expected {lo} to {hi}")
    return value


def _choice(
    raw: str | None, name: str, allowed: tuple[str, ...], default: str | None
) -> str | None:
    """A lower-cased value from ``allowed``, the default when absent, else a 422."""
    value = (raw or "").strip().lower() or default
    if value not in (default, *allowed):
        raise ApiError(422, "validation_error", f"{name}: expected {' or '.join(allowed)}")
    return value


def _weekdays(request: Request) -> tuple[str, ...]:
    """Lower-cased weekday names; anything outside monday..sunday is a 422."""
    weekdays = tuple(w.lower() for w in _csv(request, "weekday"))
    if any(w not in WEEKDAYS for w in weekdays):
        raise ApiError(422, "validation_error", "weekday: expected monday to sunday")
    return weekdays


def _list_query(request: Request, settings: Settings, today: date) -> EventListQuery:
    """Parse ``/events`` into the service's query object."""
    q = request.query_params
    date_from, date_to = _window(request, settings, today)
    status = _choice(q.get("status"), "status", ("listable", "all"), "listable")
    ids = _ids(request)
    return EventListQuery(
        ids=ids,
        date_from=date_from,
        date_to=date_to,
        place=place_input(q.get("suburb") or q.get("place"), q.get("postcode"), q.get("near")),
        within_m=_int(q.get("within_m"), "within_m", 10_000, 1, MAX_WITHIN_M),
        sports=_csv(request, "sport"),
        venue_id=(q.get("venue_id") or "").strip() or None,
        status="all" if ids else (status or "listable"),
        include_past=(q.get("include_past") or "").lower() in ("1", "true", "yes"),
        weekdays=_weekdays(request),
        time_of_day=tuple(t.lower() for t in _csv(request, "time_of_day")),
        price=_choice(q.get("price"), "price", ("free", "paid"), None),
        kinds=[KEY_TO_KIND[key] for key in parse_facilities(request)],
        limit_m=parse_band(first_of(request, "distance_m", "limit"), settings.search),
        page=_int(q.get("page"), "page", 1, 1, 10_000),
        page_size=len(ids)
        if ids
        else _int(q.get("page_size"), "page_size", settings.events.page_size, 1, MAX_PAGE_SIZE),
    )


@router.get("/events", response_model=EventListOut, response_model_exclude_none=True)
def events(
    request: Request,
    events: Events,
    settings: SettingsDep,
    now: NowDep,
    from_: DateFromQ = None,
    to: DateToQ = None,
    sport: SportsQ = None,
    suburb: SuburbQ = None,
    postcode: PostcodeQ = None,
    near: NearQ = None,
    within_m: WithinMQ = None,
    venue_id: VenueIdQ = None,
    facilities: FacilitiesQ = None,
    distance_m: DistanceQ = None,
    status: StatusQ = None,
    include_past: IncludePastQ = None,
    weekday: WeekdayQ = None,
    time_of_day: TimeOfDayQ = None,
    price: PriceQ = None,
    page: PageQ = None,
    page_size: PageSizeQ = None,
    ids: IdsQ = None,
) -> EventListOut:
    """Upcoming fixtures and weekly programs with the venue's four tiles beside each."""
    return events.list(_list_query(request, settings, now.date()), now)


@router.get("/events/sports", response_model=EventSportsOut)
def event_sports(
    request: Request,
    events: Events,
    settings: SettingsDep,
    now: NowDep,
    from_: DateFromQ = None,
    to: DateToQ = None,
) -> EventSportsOut:
    """Sports with at least one listable event in the window (feeds the filter)."""
    date_from, date_to = _window(request, settings, now.date())
    return events.sports(date_from, date_to, now)


@router.get("/events/calendar.ics", response_class=Response)
def events_calendar_file(
    request: Request, events: Events, now: NowDep, ids: IdsQ = None
) -> Response:
    """Several chosen events as one file (contract v0.3 §7.6).

    Registered before ``/events/{event_id}.ics`` so the path is not read as an
    event called ``calendar``.
    """
    chosen = _ids(request)
    if not chosen:
        raise ApiError(422, "validation_error", "ids is required: a comma list of event ids")
    file = events.calendar_file_many(chosen, now)
    return Response(
        content=file.body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file.filename}"'},
    )


@router.get("/events/{event_id}.ics", response_class=Response)
def event_calendar_file(event_id: str, events: Events, now: NowDep) -> Response:
    """One VEVENT (AC5.3.2): name, date, start time, venue address, links."""
    file = events.calendar_file(event_id, now)
    return Response(
        content=file.body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{file.filename}"'},
    )


@router.get("/events/{event_id}", response_model=EventDetailOut, response_model_exclude_none=True)
def event_detail(
    event_id: str,
    request: Request,
    events: Events,
    settings: SettingsDep,
    now: NowDep,
    distance_m: DistanceQ = None,
) -> EventDetailOut:
    """One event, the share-link target (AC5.3.3). Cancelled and past events still resolve."""
    limit_m = parse_band(first_of(request, "distance_m", "limit"), settings.search)
    return events.detail(event_id, limit_m, now)


@router.get(
    "/events/{event_id}/directions",
    response_model=EventDirectionsOut,
    response_model_exclude_none=True,
)
def event_directions(
    event_id: str,
    request: Request,
    events: Events,
    settings: SettingsDep,
    from_: OptionalOriginQ = None,
    within: WithinQ = None,
    types: TypesQ = None,
) -> EventDirectionsOut:
    """AC4.2.4 - the way to the event, and the accessible facilities on the way.

    The same machinery as ``/venues/{id}/corridor`` with the event's matched
    venue as the destination: reused, not reimplemented, because two copies
    of a corridor is two places for the disclaimer to go missing. An unmatched
    venue gets ``route_available: false`` with the reason rather than an empty
    corridor, which would read as "we looked and found nothing on the way".
    """
    return events.directions(event_id, corridor_query(request, settings))

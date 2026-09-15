"""Events (contract v0.2 section 7): list and calendar, sports, detail, calendar file."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import NowDep, Repo, SettingsDep
from app.api.params import (
    first_of,
    parse_band,
    parse_facilities,
    parse_from,
    parse_place,
    require_location,
)
from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.events import (
    WEEKDAYS,
    counts_by_date,
    empty_message,
    event_ics,
    event_out,
    in_window,
    reference_for,
    window_out,
)
from app.domain.facilities import KEY_TO_KIND, KIND_LABELS
from app.domain.presenters import venue_card_out
from app.repositories.protocols import EventFilters, EventRow, ReferencePoint, VenueRepository
from app.schemas.events import (
    EventCountsOut,
    EventDetailOut,
    EventFiltersOut,
    EventGroupOut,
    EventListOut,
    EventOut,
    EventSportOut,
    EventSportsOut,
    ShareOut,
)
from app.schemas.venues import UpcomingEventsOut

router = APIRouter()

MAX_WITHIN_M = 50_000
MAX_PAGE_SIZE = 200


def _parse_date(raw: str | None, name: str) -> date | None:
    if raw is None or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ApiError(422, "validation_error", f"{name}: expected YYYY-MM-DD") from exc


def _window(request: Request, settings: Settings, today: date) -> tuple[date, date]:
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
    out: list[str] = []
    for raw in request.query_params.getlist(name):
        out.extend(v.strip() for v in raw.split(",") if v.strip())
    return tuple(out)


def _int(raw: str | None, name: str, default: int, lo: int, hi: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiError(422, "validation_error", f"{name}: expected an integer") from exc
    if not (lo <= value <= hi):
        raise ApiError(422, "validation_error", f"{name}: expected {lo} to {hi}")
    return value


def _share_url(settings: Settings, event_id: str) -> str:
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}/events/{event_id}"


@router.get("/events", response_model=EventListOut, response_model_exclude_none=True)
def events(
    request: Request,
    repo: Repo,
    settings: SettingsDep,
    now: NowDep,
    from_: Annotated[
        str | None,
        Query(alias="from", description="YYYY-MM-DD, local date, inclusive. Default today."),
    ] = None,
    to: Annotated[
        str | None,
        Query(description="YYYY-MM-DD, inclusive. Default from + default_window_days."),
    ] = None,
    sport: Annotated[
        str | None, Query(description="A name from /sports or /events/sports; comma list allowed.")
    ] = None,
    suburb: Annotated[str | None, Query(description='"Preston 3072" or "Preston".')] = None,
    postcode: Annotated[str | None, Query(description="Four digits.")] = None,
    near: Annotated[str | None, Query(description='"lat,lon" from browser geolocation.')] = None,
    within_m: Annotated[
        int | None, Query(description="Radius around the place, metres. Default 10000.")
    ] = None,
    venue_id: Annotated[str | None, Query(description="Events at one venue.")] = None,
    facilities: Annotated[
        list[str] | None,
        Query(
            description="Access requirements, comma list of facility types. Groups; never hides."
        ),
    ] = None,
    distance_m: Annotated[
        int | None, Query(description="Band the facilities are evaluated at. Default from /config.")
    ] = None,
    status: Annotated[
        str | None, Query(description="listable (default) or all.", examples=["listable"])
    ] = None,
    include_past: Annotated[
        bool | None, Query(description="Also fixtures already started inside the window.")
    ] = None,
    weekday: Annotated[
        str | None, Query(description="Programs on these weekdays, comma list, e.g. saturday.")
    ] = None,
    time_of_day: Annotated[
        str | None, Query(description="morning, afternoon, evening, after_school; comma list.")
    ] = None,
    price: Annotated[str | None, Query(description="free or paid.")] = None,
    page: Annotated[int | None, Query(description="1-based.")] = None,
    page_size: Annotated[int | None, Query(description="Default from /config, max 200.")] = None,
) -> EventListOut:
    """Upcoming fixtures and weekly programs with the venue's four tiles beside each."""
    q = request.query_params
    cfg = settings.search
    date_from, date_to = _window(request, settings, now.date())

    keys = parse_facilities(request)
    kinds = [KEY_TO_KIND[key] for key in keys]
    limit_m = parse_band(first_of(request, "distance_m", "limit"), cfg)
    status_value = (q.get("status") or "listable").strip().lower()
    if status_value not in ("listable", "all"):
        raise ApiError(422, "validation_error", "status: expected listable or all")
    price_value = (q.get("price") or "").strip().lower() or None
    if price_value not in (None, "free", "paid"):
        raise ApiError(422, "validation_error", "price: expected free or paid")
    weekdays = tuple(w.lower() for w in _csv(request, "weekday"))
    if any(w not in WEEKDAYS for w in weekdays):
        raise ApiError(422, "validation_error", "weekday: expected monday to sunday")
    page_no = _int(q.get("page"), "page", 1, 1, 10_000)
    size = _int(q.get("page_size"), "page_size", settings.events.page_size, 1, MAX_PAGE_SIZE)
    within = _int(q.get("within_m"), "within_m", 10_000, 1, MAX_WITHIN_M)

    reference: ReferencePoint | None = None
    place: str | None = None
    near_raw = q.get("near")
    if near_raw and near_raw.strip():
        reference = parse_from(near_raw, repo)
        place = "your location"
    else:
        sub, pc = parse_place(q.get("suburb") or q.get("place"), q.get("postcode"))
        if sub or pc:
            place = " ".join(p for p in (sub, pc) if p)
            reference = require_location(repo, sub, pc, place)

    filters = EventFilters(
        date_from=date_from,
        date_to=date_to,
        now=now,
        sports=_csv(request, "sport"),
        reference=reference,
        within_m=within,
        venue_id=(q.get("venue_id") or "").strip() or None,
        status=status_value,
        include_past=(q.get("include_past") or "").lower() in ("1", "true", "yes"),
        weekdays=weekdays,
        time_of_day=tuple(t.lower() for t in _csv(request, "time_of_day")),
        price=price_value,
    )
    rows = [r for r in repo.list_events(filters) if in_window(r, date_from, date_to)]

    built = [
        event_out(r, limit_m=limit_m, stale_default=cfg.default_stale_after_days, kinds=kinds)
        for r in rows
    ]
    matched = [b.out for b in built if b.group in (None, "matched")]
    undocumented = [b.out for b in built if b.group == "undocumented"]
    not_available = [b.out for b in built if b.group == "not_available"]

    def page_of(items: list[EventOut]) -> list[EventOut]:
        start = (page_no - 1) * size
        return items[start : start + size]

    labels = [KIND_LABELS[k].lower() for k in kinds]
    joined = ""
    if len(labels) == 1:
        joined = labels[0]
    elif labels:
        joined = ", ".join(labels[:-1]) + " or " + labels[-1]
    counts = EventCountsOut(
        total=len(rows),
        fixtures=sum(1 for r in rows if r.kind == "fixture"),
        programs=sum(1 for r in rows if r.kind == "program"),
        by_date=counts_by_date(rows, date_from, date_to),
        unmatched_venue=sum(1 for r in rows if r.venue is None),
        matched=len(matched) if kinds else None,
        undocumented=len(undocumented) if kinds else None,
        not_available=len(not_available) if kinds else None,
    )
    attribution = sorted({r.source_attribution for r in rows if r.source_attribution})
    return EventListOut(
        window=window_out(date_from, date_to, settings.timezone),
        filters=EventFiltersOut(
            sport=list(filters.sports),
            status=status_value,
            facilities_requested=kinds,
            distance_limit_m=limit_m,
            within_m=within if reference is not None else None,
            venue_id=filters.venue_id,
            weekday=list(weekdays),
            time_of_day=list(filters.time_of_day),
            price=price_value,
        ),
        reference_point=reference_for(reference),
        counts=counts,
        page=page_no,
        page_size=size,
        events=page_of(matched),
        undocumented_group=EventGroupOut(
            label=f"{len(undocumented)} more with no published information about {joined}",
            count=len(undocumented),
            events=page_of(undocumented),
        )
        if kinds
        else None,
        not_available_group=EventGroupOut(
            label=f"{len(not_available)} at venues that record they do not have {joined}",
            count=len(not_available),
            events=page_of(not_available),
        )
        if kinds
        else None,
        attribution=attribution,
        empty_message=empty_message(filters.sports, date_from, date_to, place)
        if not rows
        else None,
    )


@router.get("/events/sports", response_model=EventSportsOut)
def event_sports(
    request: Request,
    repo: Repo,
    settings: SettingsDep,
    now: NowDep,
    from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None,
) -> EventSportsOut:
    """Sports with at least one listable event in the window (feeds the filter)."""
    date_from, date_to = _window(request, settings, now.date())
    rows = repo.event_sports(date_from, date_to, now)
    return EventSportsOut(
        window=window_out(date_from, date_to, settings.timezone),
        sports=[EventSportOut(name=r.name, event_count=r.event_count) for r in rows],
    )


def _load(repo: VenueRepository, event_id: str) -> EventRow:
    row = repo.get_event(event_id)
    if row is None:
        raise ApiError(404, "event_not_found", f"No event with id {event_id!r}.")
    return row


@router.get("/events/{event_id}.ics", response_class=Response)
def event_calendar_file(event_id: str, repo: Repo, settings: SettingsDep, now: NowDep) -> Response:
    """One VEVENT (AC5.3.2): name, date, start time, venue address, links."""
    row = _load(repo, event_id)
    cfg = settings.search
    built = event_out(
        row, limit_m=cfg.default_distance_m, stale_default=cfg.default_stale_after_days, kinds=[]
    )
    body = event_ics(row, built.out, _share_url(settings, event_id), now=now)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="sportable-{event_id}.ics"'},
    )


@router.get("/events/{event_id}", response_model=EventDetailOut, response_model_exclude_none=True)
def event_detail(
    event_id: str,
    request: Request,
    repo: Repo,
    settings: SettingsDep,
    now: NowDep,
    distance_m: Annotated[int | None, Query(description="Band for the tiles.")] = None,
) -> EventDetailOut:
    """One event, the share-link target (AC5.3.3). Cancelled and past events still resolve."""
    row = _load(repo, event_id)
    cfg = settings.search
    limit_m = parse_band(first_of(request, "distance_m", "limit"), cfg)
    built = event_out(row, limit_m=limit_m, stale_default=cfg.default_stale_after_days, kinds=[])
    card = None
    if row.venue is not None:
        upcoming = repo.upcoming_events(row.venue.venue_id, now)
        card = venue_card_out(
            row.venue,
            None,
            limit_m,
            cfg.default_stale_after_days,
            UpcomingEventsOut(
                count=upcoming.count,
                next_starts_at=upcoming.next_starts_at.isoformat()
                if upcoming.next_starts_at
                else None,
                href=f"/events?venue_id={row.venue.venue_id}" if upcoming.count else None,
            ),
        )
    return EventDetailOut(
        **built.out.model_dump(),
        venue_card=card,
        share=ShareOut(url=_share_url(settings, event_id)),
    )

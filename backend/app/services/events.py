"""Events (contract v0.2 section 7): list, sports, detail, calendar file, directions."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.events import (
    STATUS_LABELS,
    Built,
    counts_by_date,
    empty_message,
    event_ics,
    event_out,
    in_window,
    local_time,
    recurrence_out,
    reference_for,
    window_out,
)
from app.domain.facilities import KIND_LABELS
from app.domain.presenters import venue_card_out
from app.domain.summary import event_summary_sentences
from app.repositories.protocols import (
    EventFilters,
    EventRepository,
    EventRow,
    ReferencePoint,
    VenueRepository,
)
from app.schemas.events import (
    DirectionsEventOut,
    EventCountsOut,
    EventDetailOut,
    EventDirectionsOut,
    EventFiltersOut,
    EventGroupOut,
    EventListOut,
    EventOut,
    EventSportOut,
    EventSportsOut,
    RoutingProviderOut,
    ShareOut,
)
from app.services.inputs import CorridorQuery, EventListQuery
from app.services.locations import LocationService
from app.services.venues import corridor_for, upcoming_events_out

# DS-05's card in the source register says nothing it returns is stored and no
# facility status ever traces to it. Both remain true here: the corridor is
# PostGIS over the amenity table, so the routing provider is credited and
# explained without being called.
ROUTING_PROVIDER = "openrouteservice (DS-05)"
ROUTING_NOT_USED_NOTE = (
    "No routing request was made. The path shown is a straight-line corridor computed "
    "from our own facility data (ADR-003), not a checked route, so this page uses none "
    "of the openrouteservice request quota and cannot fail if that service is rate "
    "limited or unavailable. Nothing openrouteservice returns is stored."
)


@dataclass(frozen=True)
class CalendarFile:
    """An iCalendar body and the filename to serve it under."""

    body: str
    filename: str


def _joined_labels(kinds: Sequence[str]) -> str:
    """``accessible toilet, accessible parking or step-free railway station``."""
    labels = [KIND_LABELS[k].lower() for k in kinds]
    if len(labels) <= 1:
        return labels[0] if labels else ""
    return ", ".join(labels[:-1]) + " or " + labels[-1]


def _filters(
    query: EventListQuery, reference: ReferencePoint | None, now: datetime
) -> EventFilters:
    """The repository filters for a list query, once the place is resolved."""
    return EventFilters(
        date_from=query.date_from,
        date_to=query.date_to,
        now=now,
        sports=query.sports,
        reference=reference,
        within_m=query.within_m,
        venue_id=query.venue_id,
        status=query.status,
        include_past=query.include_past,
        weekdays=query.weekdays,
        time_of_day=query.time_of_day,
        price=query.price,
    )


def _filters_out(query: EventListQuery, reference: ReferencePoint | None) -> EventFiltersOut:
    """Echo of the filters applied, as the contract shows them."""
    return EventFiltersOut(
        sport=list(query.sports),
        status=query.status,
        facilities_requested=query.kinds,
        distance_limit_m=query.limit_m,
        within_m=query.within_m if reference is not None else None,
        venue_id=query.venue_id,
        weekday=list(query.weekdays),
        time_of_day=list(query.time_of_day),
        price=query.price,
    )


def _counts(
    rows: list[EventRow], groups: dict[str, list[EventOut]], query: EventListQuery
) -> EventCountsOut:
    """Totals for the list, with the three group counts only when a filter applied."""
    filtered = bool(query.kinds)
    return EventCountsOut(
        total=len(rows),
        fixtures=sum(1 for r in rows if r.kind == "fixture"),
        programs=sum(1 for r in rows if r.kind == "program"),
        by_date=counts_by_date(rows, query.date_from, query.date_to),
        unmatched_venue=sum(1 for r in rows if r.venue is None),
        matched=len(groups["matched"]) if filtered else None,
        undocumented=len(groups["undocumented"]) if filtered else None,
        not_available=len(groups["not_available"]) if filtered else None,
    )


def _group_out(label: str, items: list[EventOut], query: EventListQuery) -> EventGroupOut | None:
    """One page of a secondary group, or None when no facility filter applied."""
    if not query.kinds:
        return None
    return EventGroupOut(label=label, count=len(items), events=_page(items, query))


def _page(items: list[EventOut], query: EventListQuery) -> list[EventOut]:
    """The requested page of a list."""
    start = (query.page - 1) * query.page_size
    return items[start : start + query.page_size]


def _grouped(built: list[Built]) -> dict[str, list[EventOut]]:
    """Split built events into the three groups; no filter puts everything in matched."""
    return {
        "matched": [b.out for b in built if b.group in (None, "matched")],
        "undocumented": [b.out for b in built if b.group == "undocumented"],
        "not_available": [b.out for b in built if b.group == "not_available"],
    }


def _directions_event_out(row: EventRow) -> DirectionsEventOut:
    """Just enough of the event to caption the directions map."""
    local = local_time(row)
    recurrence = recurrence_out(row)
    return DirectionsEventOut(
        id=row.event_id,
        kind="program" if row.kind == "program" else "fixture",
        title=row.title,
        status=row.status,
        status_label=STATUS_LABELS.get(row.status, row.status.title()),
        starts_at=local.isoformat() if local else None,
        date_local=local.date().isoformat() if local else None,
        time_local=local.strftime("%H:%M") if local else None,
        timezone=row.timezone,
        recurrence_summary=recurrence.summary if recurrence else None,
        href=f"/events/{row.event_id}",
    )


def _no_route_out(row: EventRow) -> EventDirectionsOut:
    """``route_available: false`` for an unmatched venue, with the reason (AC4.2.3)."""
    named = f", {row.venue_name}," if row.venue_name else ""
    return EventDirectionsOut(
        event=_directions_event_out(row),
        route_available=False,
        reason="venue_not_matched",
        message=(
            f"The venue for this event{named} is not in our venue list, so we cannot "
            "show a route to it or the accessible facilities on the way. The address "
            "the publisher gave is on the event page."
        ),
        corridor=None,
        routing=_routing(),
    )


def _routing() -> RoutingProviderOut:
    """What was (not) asked of the routing provider: nothing, by design."""
    return RoutingProviderOut(
        provider=ROUTING_PROVIDER, status="not_used", note=ROUTING_NOT_USED_NOTE
    )


@dataclass(frozen=True)
class EventService:
    """Event use cases over the event repository, with venues for the corridor."""

    events: EventRepository
    venues: VenueRepository
    locations: LocationService
    settings: Settings

    def load(self, event_id: str) -> EventRow:
        """The event row, or a 404 ``event_not_found``."""
        row = self.events.get_event(event_id)
        if row is None:
            raise ApiError(404, "event_not_found", f"No event with id {event_id!r}.")
        return row

    def _built(self, row: EventRow, limit_m: int, kinds: Sequence[str]) -> Built:
        """The event response object at the band, with the venue's tiles."""
        stale = self.settings.search.default_stale_after_days
        return event_out(row, limit_m=limit_m, stale_default=stale, kinds=kinds)

    def _share_url(self, event_id: str) -> str:
        """Absolute link to the event page on this environment's site."""
        base = (self.settings.public_base_url or "").rstrip("/")
        return f"{base}/events/{event_id}"

    def list(self, query: EventListQuery, now: datetime) -> EventListOut:
        """Upcoming fixtures and weekly programs with the venue's four tiles beside each."""
        reference = self.locations.resolve_optional(query.place)
        place = _place_label(query, reference)
        rows = self.events.list_events(_filters(query, reference, now))
        rows = [r for r in rows if in_window(r, query.date_from, query.date_to)]
        groups = _grouped([self._built(r, query.limit_m, query.kinds) for r in rows])
        joined = _joined_labels(query.kinds)
        return EventListOut(
            window=window_out(query.date_from, query.date_to, self.settings.timezone),
            filters=_filters_out(query, reference),
            reference_point=reference_for(reference),
            counts=_counts(rows, groups, query),
            page=query.page,
            page_size=query.page_size,
            events=_page(groups["matched"], query),
            undocumented_group=_group_out(
                f"{len(groups['undocumented'])} more with no published information about {joined}",
                groups["undocumented"],
                query,
            ),
            not_available_group=_group_out(
                f"{len(groups['not_available'])} at venues that record they do not have {joined}",
                groups["not_available"],
                query,
            ),
            attribution=sorted({r.source_attribution for r in rows if r.source_attribution}),
            empty_message=empty_message(query.sports, query.date_from, query.date_to, place)
            if not rows
            else None,
        )

    def sports(self, date_from: date, date_to: date, now: datetime) -> EventSportsOut:
        """Sports with at least one listable event in the window (feeds the filter)."""
        rows = self.events.event_sports(date_from, date_to, now)
        return EventSportsOut(
            window=window_out(date_from, date_to, self.settings.timezone),
            sports=[EventSportOut(name=r.name, event_count=r.event_count) for r in rows],
        )

    def detail(self, event_id: str, limit_m: int, now: datetime) -> EventDetailOut:
        """One event, the share-link target (AC5.3.3). Cancelled and past events still resolve."""
        row = self.load(event_id)
        built = self._built(row, limit_m, [])
        card = None
        if row.venue is not None:
            card = venue_card_out(
                row.venue,
                None,
                limit_m,
                self.settings.search.default_stale_after_days,
                upcoming_events_out(self.events, row.venue.venue_id, now),
            )
        return EventDetailOut(
            **built.out.model_dump(),
            venue_card=card,
            share=ShareOut(url=self._share_url(event_id)),
            # US3.3. Built from the same object the page renders, so Read Aloud
            # cannot speak a facility status the page does not show.
            summary_sentences=event_summary_sentences(built.out),
        )

    def calendar_file(self, event_id: str, now: datetime) -> CalendarFile:
        """One VEVENT (AC5.3.2): name, date, start time, venue address, links."""
        row = self.load(event_id)
        built = self._built(row, self.settings.search.default_distance_m, [])
        body = event_ics(row, built.out, self._share_url(event_id), now=now)
        return CalendarFile(body=body, filename=f"sportable-{event_id}.ics")

    def directions(self, event_id: str, query: CorridorQuery) -> EventDirectionsOut:
        """AC4.2.4: the venue corridor pointed at the event's matched venue.

        An unmatched venue has no geometry to draw a line to, so the answer is
        ``route_available: false`` with the reason, checked before ``from`` is
        required: asking for a starting point and then saying no wastes a step.
        """
        row = self.load(event_id)
        if row.venue is None:
            return _no_route_out(row)
        corridor = corridor_for(self.venues, self.locations, self.settings, row.venue, query)
        return EventDirectionsOut(
            event=_directions_event_out(row),
            route_available=True,
            reason=None,
            message=(
                f"Facilities recorded within {query.within_m} m of a straight line from "
                f"{corridor.origin.label} to {row.venue.name}, where this event is held."
            ),
            corridor=corridor,
            routing=_routing(),
        )


def _place_label(query: EventListQuery, reference: ReferencePoint | None) -> str | None:
    """The place as typed, for the empty message; None when no place was given."""
    if reference is None or query.place is None:
        return None
    return "your location" if query.place.point is not None else query.place.typed

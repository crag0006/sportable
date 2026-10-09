"""Search, the venue page and the corridor (contract v0.2 sections 4 to 6)."""

from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.facilities import KEY_TO_KIND, FrontendKey, group
from app.domain.presenters import corridor_out, search_out, venue_card_out
from app.repositories.protocols import EventRepository, VenueRepository, VenueRow
from app.schemas.venues import CorridorOut, SearchOut, UpcomingEventsOut, VenueCardOut
from app.services.inputs import CorridorQuery, SearchQuery, VenuePageQuery
from app.services.locations import LocationService

# US2.2 names these three; change facilities are available on request.
DEFAULT_CORRIDOR_TYPES: tuple[FrontendKey, ...] = ("toilet", "parking", "stop")


def upcoming_events_out(events: EventRepository, venue_id: str, now: datetime) -> UpcomingEventsOut:
    """The upcoming-events block of a venue card, from the event repository."""
    upcoming = events.upcoming_events(venue_id, now)
    return UpcomingEventsOut(
        count=upcoming.count,
        next_starts_at=upcoming.next_starts_at.isoformat() if upcoming.next_starts_at else None,
        href=f"/events?venue_id={venue_id}" if upcoming.count else None,
    )


def corridor_for(
    venues: VenueRepository,
    locations: LocationService,
    settings: Settings,
    venue: VenueRow,
    query: CorridorQuery,
) -> CorridorOut:
    """The straight-line corridor to a venue (ADR-003). Shared with event directions.

    There is no default origin (AC2.2.1): a missing ``from`` is a 422.
    """
    origin = locations.resolve_optional(query.origin)
    if origin is None:
        raise ApiError(
            422,
            "validation_error",
            "from is required: a suburb, postcode or latitude,longitude starting point",
        )
    keys = query.keys or list(DEFAULT_CORRIDOR_TYPES)
    result = venues.corridor(origin, venue, query.within_m, [KEY_TO_KIND[k] for k in keys])
    return corridor_out(
        venue, origin, query.within_m, keys, result, settings.search.default_stale_after_days
    )


@dataclass(frozen=True)
class VenueService:
    """Venue use cases: search, page, corridor."""

    venues: VenueRepository
    events: EventRepository
    locations: LocationService
    settings: Settings

    def load(self, venue_id: str) -> VenueRow:
        """The venue row, or a 404 ``venue_not_found``."""
        row = self.venues.get_venue(venue_id)
        if row is None:
            raise ApiError(404, "venue_not_found", f"No venue with id {venue_id!r}.")
        return row

    def search(self, query: SearchQuery) -> SearchOut:
        """Venues for a sport near a place, in three groups (contract v0.2 §4)."""
        cfg = self.settings.search
        reference = self.locations.resolve_place(query.place)
        place = "your location" if query.place.point is not None else query.place.typed
        venues = self.venues.search(query.sport, reference, cfg.search_radius_m)
        groups = group(venues, query.kinds, query.limit_m)
        latest = max((v.retrieved_at for v in venues if v.retrieved_at is not None), default=None)
        return search_out(
            sport=query.sport,
            reference=reference,
            limit_m=query.limit_m,
            radius_m=cfg.search_radius_m,
            kinds=query.kinds,
            total=len(venues),
            groups=groups,
            max_results=cfg.max_results,
            stale_default=cfg.default_stale_after_days,
            place=place,
            retrieved_at=latest,
        )

    def page(self, query: VenuePageQuery, now: datetime) -> VenueCardOut:
        """The venue page (contract v0.2 §5), with distance when ``from`` was given."""
        row = self.load(query.venue_id)
        reference = self.locations.resolve_optional(query.origin)
        return venue_card_out(
            row,
            reference,
            query.limit_m,
            self.settings.search.default_stale_after_days,
            upcoming_events_out(self.events, query.venue_id, now),
        )

    def corridor(self, venue_id: str, query: CorridorQuery) -> CorridorOut:
        """US2.2 / US2.3: the straight-line corridor to the venue. Not a route."""
        return corridor_for(self.venues, self.locations, self.settings, self.load(venue_id), query)

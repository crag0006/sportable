"""FastAPI dependencies.

Routes receive services, never repositories. Tests override the three
repository factories with in-memory fakes and ``get_now`` with a fixed
instant; the services are then built over the fakes without knowing.
"""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.repositories.postgres_events import PostgresEventRepository
from app.repositories.postgres_reference import PostgresReferenceRepository
from app.repositories.postgres_venues import PostgresVenueRepository
from app.repositories.protocols import EventRepository, ReferenceRepository, VenueRepository
from app.services.events import EventService
from app.services.locations import LocationService
from app.services.reference import ReferenceService
from app.services.venues import VenueService


def get_reference_repository() -> ReferenceRepository:
    """The reference repository; overridden in tests."""
    return PostgresReferenceRepository()


def get_venue_repository() -> VenueRepository:
    """The venue repository; overridden in tests."""
    return PostgresVenueRepository()


def get_event_repository() -> EventRepository:
    """The event repository; overridden in tests."""
    return PostgresEventRepository()


def get_now() -> datetime:
    """The current instant in the site's timezone. One place, so tests can freeze it."""
    return datetime.now(ZoneInfo(get_settings().timezone))


ReferenceRepo = Annotated[ReferenceRepository, Depends(get_reference_repository)]
VenueRepo = Annotated[VenueRepository, Depends(get_venue_repository)]
EventRepo = Annotated[EventRepository, Depends(get_event_repository)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
NowDep = Annotated[datetime, Depends(get_now)]


def get_location_service(reference: ReferenceRepo) -> LocationService:
    """Place resolution over the reference repository."""
    return LocationService(reference)


Locations = Annotated[LocationService, Depends(get_location_service)]


def get_reference_service(reference: ReferenceRepo, settings: SettingsDep) -> ReferenceService:
    """Sports, suburbs and sources."""
    return ReferenceService(reference, settings)


def get_venue_service(
    venues: VenueRepo, events: EventRepo, locations: Locations, settings: SettingsDep
) -> VenueService:
    """Search, venue page and corridor."""
    return VenueService(venues, events, locations, settings)


def get_event_service(
    events: EventRepo, venues: VenueRepo, locations: Locations, settings: SettingsDep
) -> EventService:
    """Events list, detail, calendar file and directions."""
    return EventService(events, venues, locations, settings)


References = Annotated[ReferenceService, Depends(get_reference_service)]
Venues = Annotated[VenueService, Depends(get_venue_service)]
Events = Annotated[EventService, Depends(get_event_service)]

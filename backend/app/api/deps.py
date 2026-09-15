"""FastAPI dependencies. Tests override ``get_repository`` with an in-memory
fake and ``get_now`` with a fixed instant."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.repositories.postgres import PostgresVenueRepository
from app.repositories.protocols import VenueRepository


def get_repository() -> VenueRepository:
    return PostgresVenueRepository()


def get_now() -> datetime:
    """The current instant in the site's timezone. One place, so tests can freeze it."""
    return datetime.now(ZoneInfo(get_settings().timezone))


Repo = Annotated[VenueRepository, Depends(get_repository)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
NowDep = Annotated[datetime, Depends(get_now)]

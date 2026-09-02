"""FastAPI dependencies. Tests override ``get_repository`` with an in-memory fake."""

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.repositories.postgres import PostgresVenueRepository
from app.repositories.protocols import VenueRepository


def get_repository() -> VenueRepository:
    return PostgresVenueRepository()


Repo = Annotated[VenueRepository, Depends(get_repository)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

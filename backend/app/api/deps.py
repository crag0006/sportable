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
from app.gateways.bedrock import BedrockChatModel, TitanEmbeddingModel
from app.gateways.protocols import ChatModel, EmbeddingModel
from app.repositories.postgres_chunks import PostgresChunkRepository
from app.repositories.postgres_events import PostgresEventRepository
from app.repositories.postgres_reference import PostgresReferenceRepository
from app.repositories.postgres_venues import PostgresVenueRepository
from app.repositories.protocols import (
    ChunkRepository,
    EventRepository,
    ReferenceRepository,
    VenueRepository,
)
from app.services.assistant.retrieval import Retrieval
from app.services.assistant.service import AssistantService
from app.services.assistant.tools import ToolRunner
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


# ------------------------------------------------------------- assistant
def get_chat_model(settings: SettingsDep) -> ChatModel:
    """Claude on Bedrock; overridden in tests with a scripted fake."""
    return BedrockChatModel(settings)


def get_embedding_model(settings: SettingsDep) -> EmbeddingModel:
    """Titan on Bedrock; overridden in tests."""
    return TitanEmbeddingModel(settings)


def get_chunk_repository() -> ChunkRepository:
    """The retrieval index; overridden in tests."""
    return PostgresChunkRepository()


ChatDep = Annotated[ChatModel, Depends(get_chat_model)]
EmbedDep = Annotated[EmbeddingModel, Depends(get_embedding_model)]
ChunkRepo = Annotated[ChunkRepository, Depends(get_chunk_repository)]


def get_assistant_service(
    chat: ChatDep,
    embeddings: EmbedDep,
    chunks: ChunkRepo,
    reference: ReferenceRepo,
    venues: Venues,
    events: Events,
    locations: Locations,
    references: References,
    settings: SettingsDep,
    now: NowDep,
) -> AssistantService:
    """The assistant over the model gateways, the retrieval index and the four services."""
    retrieval = Retrieval(
        chunks, embeddings, settings.bedrock_embedding_model_id, settings.assistant
    )
    runner = ToolRunner(venues, events, locations, references, reference, retrieval, settings, now)
    return AssistantService(chat, runner, settings, now)


Assistant = Annotated[AssistantService, Depends(get_assistant_service)]

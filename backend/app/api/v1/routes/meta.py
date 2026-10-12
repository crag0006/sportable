"""Reference endpoints: health, config, sports, suburbs, locations, sources, legend."""

from fastapi import APIRouter

from app.api.deps import Locations, References, SettingsDep
from app.api.params import parse_origin
from app.api.queries import ResolveQ, TypeaheadQ
from app.schemas.legend import FacilityTypesOut
from app.schemas.locations import ResolveOut
from app.schemas.sources import SourcesOut
from app.schemas.venues import ConfigOut, HealthOut, SportsOut, SuburbsOut
from app.services.inputs import PlaceInput
from app.services.reference import config_out, facility_types_out

router = APIRouter(tags=["Reference"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Liveness only; says nothing about the database."""
    return HealthOut()


@router.get("/config", response_model=ConfigOut)
def config(settings: SettingsDep) -> ConfigOut:
    """The distance bands and defaults the interface renders (AC1.2.4)."""
    return config_out(settings)


@router.get("/sports", response_model=SportsOut)
def sports(references: References, q: TypeaheadQ = None) -> SportsOut:
    """Only sports that exist in loaded venues (AC1.1.1)."""
    return references.sports(q)


@router.get("/facility-types", response_model=FacilityTypesOut)
def facility_types() -> FacilityTypesOut:
    """The map legend, as data (US3.1)."""
    return facility_types_out()


@router.get("/suburbs", response_model=SuburbsOut)
def suburbs(references: References) -> SuburbsOut:
    """Suburb and postcode pairs for the dropdown."""
    return references.places()


@router.get("/locations/resolve", response_model=ResolveOut, response_model_exclude_none=True)
def resolve(locations: Locations, q: ResolveQ) -> ResolveOut:
    """Three outcomes, never an empty answer (AC1.1.4)."""
    typed = q.strip()
    place = parse_origin(typed) or PlaceInput()
    return locations.resolve_query(place, typed)


@router.get("/sources", response_model=SourcesOut, response_model_exclude_none=True)
def sources(references: References) -> SourcesOut:
    """The register behind the Sources and licences page (constraint C2)."""
    return references.sources()

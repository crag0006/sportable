"""Reference endpoints: health, config, sports, suburbs, locations, sources."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import Repo, SettingsDep
from app.api.params import COVERAGE_DESCRIPTION, parse_place, parse_point
from app.domain.presenters import reference_out, register_source_out
from app.schemas.locations import CoverageOut, MatchedOut, ResolveOut, SuggestionOut
from app.schemas.sources import SourcesOut
from app.schemas.venues import (
    ConfigOut,
    EventsConfigOut,
    HealthOut,
    SportOut,
    SportsOut,
    SuburbOut,
    SuburbsOut,
)

router = APIRouter()

COVERAGE_EXAMPLES = ["Melbourne", "Darebin", "Geelong", "Ballarat", "Bendigo"]


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut()


@router.get("/config", response_model=ConfigOut)
def config(settings: SettingsDep) -> ConfigOut:
    cfg = settings.search
    ev = settings.events
    return ConfigOut(
        distance_bands_m=cfg.distance_bands_m,
        default_distance_m=cfg.default_distance_m,
        search_radius_m=cfg.search_radius_m,
        corridor_default_m=cfg.corridor_default_m,
        max_results=cfg.max_results,
        events=EventsConfigOut(
            default_window_days=ev.default_window_days,
            max_window_days=ev.max_window_days,
            page_size=ev.page_size,
        ),
        timezone=settings.timezone,
        default_stale_after_days=cfg.default_stale_after_days,
        source=cfg.source,
    )


@router.get("/sports", response_model=SportsOut)
def sports(
    repo: Repo,
    q: Annotated[
        str | None,
        Query(description="Optional typeahead filter, case-insensitive.", examples=["net"]),
    ] = None,
) -> SportsOut:
    """Only sports that exist in loaded venues (AC1.1.1)."""
    return SportsOut(
        sports=[
            SportOut(name=s.name, venue_count=s.venue_count, event_count=s.event_count)
            for s in repo.list_sports(q)
        ]
    )


@router.get("/suburbs", response_model=SuburbsOut)
def suburbs(repo: Repo) -> SuburbsOut:
    return SuburbsOut(
        suburbs=[
            SuburbOut(suburb=p.suburb, postcode=p.postcode, label=f"{p.suburb} {p.postcode}")
            for p in repo.list_places()
        ]
    )


@router.get("/locations/resolve", response_model=ResolveOut, response_model_exclude_none=True)
def resolve(
    repo: Repo,
    q: Annotated[
        str,
        Query(
            description='A suburb ("Preston"), suburb and postcode ("Preston 3072"), '
            'a postcode ("3072") or "lat,lon".',
            examples=["Preston 3072"],
        ),
    ],
) -> ResolveOut:
    """Three outcomes, never an empty answer (AC1.1.4)."""
    typed = q.strip()
    point = parse_point(typed)
    if point is not None:
        return ResolveOut(
            outcome="resolved",
            query=typed,
            reference_point=reference_out(point),
            matched=MatchedOut(label=point.label, kind="point"),
        )
    suburb, postcode = parse_place(typed, None)
    match = repo.resolve_location(suburb, postcode)
    if match.outcome == "resolved" and match.reference is not None:
        kind = "postcode" if match.reference.kind == "postcode" else "suburb"
        return ResolveOut(
            outcome="resolved",
            query=typed,
            reference_point=reference_out(match.reference),
            matched=MatchedOut(label=match.matched_label or typed, kind=kind),
        )
    if match.outcome == "outside_coverage":
        label = match.matched_label or typed
        return ResolveOut(
            outcome="outside_coverage",
            query=typed,
            matched=MatchedOut(
                label=label, kind="postcode" if match.matched_kind == "postcode" else "suburb"
            ),
            message=f"{label} is outside the area SportAble covers. {COVERAGE_DESCRIPTION}",
            coverage=CoverageOut(description=COVERAGE_DESCRIPTION, examples=COVERAGE_EXAMPLES),
        )
    return ResolveOut(
        outcome="unresolved",
        query=typed,
        message=f"We could not find a suburb or postcode matching {typed!r}.",
        suggestions=[
            SuggestionOut(
                label=s.label, kind="postcode" if s.kind == "postcode" else "suburb", code=s.code
            )
            for s in match.suggestions
        ],
    )


@router.get("/sources", response_model=SourcesOut, response_model_exclude_none=True)
def sources(repo: Repo, settings: SettingsDep) -> SourcesOut:
    """The register behind the Sources and licences page (constraint C2)."""
    stale_default = settings.search.default_stale_after_days
    return SourcesOut(
        sources=[register_source_out(row, stale_default) for row in repo.list_sources()]
    )

"""Reference endpoints: config, sports, suburbs, the legend and the source register."""

from dataclasses import dataclass

from app.core.config import Settings
from app.domain.legend import LEGEND, LEGEND_HEADING, LEGEND_NOTE, screen_reader_summary
from app.domain.presenters import register_source_out
from app.repositories.protocols import ReferenceRepository
from app.schemas.legend import FacilityTypeOut, FacilityTypesOut
from app.schemas.sources import SourcesOut
from app.schemas.venues import (
    ConfigOut,
    EventsConfigOut,
    SportOut,
    SportsOut,
    SuburbOut,
    SuburbsOut,
)


def facility_types_out() -> FacilityTypesOut:
    """The map legend as data (US3.1).

    No repository on purpose. This vocabulary is the ``amenity_kind`` enum: it
    changes when a migration changes it and at no other time, so a database
    round trip per page load would buy nothing and would add a way for the
    legend to be unavailable while the markers it explains are drawn anyway.
    ``data/sql/011_vocabulary_and_summary.sql`` holds the matching
    ``facility_legend`` view, and ``tests/unit/test_legend.py`` fails if the
    two ever disagree. ``screen_reader_summary`` (AC3.1.4) is built from the
    same rows the map draws.
    """
    return FacilityTypesOut(
        heading=LEGEND_HEADING,
        facility_types=[
            FacilityTypeOut(
                type=entry.kind,
                label=entry.display_label,
                shape=entry.shape,
                colour_token=entry.colour_token,
                colour_hex=entry.colour_hex,
                description=entry.description,
                screen_reader_text=entry.screen_reader_text,
            )
            for entry in LEGEND
        ],
        note=LEGEND_NOTE,
        screen_reader_summary=screen_reader_summary(),
    )


def config_out(settings: Settings) -> ConfigOut:
    """The values the interface renders for AC1.2.4 plus the event window defaults."""
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


@dataclass(frozen=True)
class ReferenceService:
    """Sports, suburbs and sources, read from the reference repository."""

    reference: ReferenceRepository
    settings: Settings

    def sports(self, q: str | None) -> SportsOut:
        """Only sports that exist in loaded venues or programmes (AC1.1.1)."""
        return SportsOut(
            sports=[
                SportOut(name=s.name, venue_count=s.venue_count, event_count=s.event_count)
                for s in self.reference.list_sports(q)
            ]
        )

    def places(self) -> SuburbsOut:
        """Suburb and postcode pairs for the dropdown, with a display label."""
        return SuburbsOut(
            suburbs=[
                SuburbOut(suburb=p.suburb, postcode=p.postcode, label=f"{p.suburb} {p.postcode}")
                for p in self.reference.list_places()
            ]
        )

    def sources(self) -> SourcesOut:
        """The register behind the Sources and licences page (constraint C2)."""
        stale_default = self.settings.search.default_stale_after_days
        return SourcesOut(
            sources=[
                register_source_out(row, stale_default) for row in self.reference.list_sources()
            ]
        )

"""Turn what a person typed for a place into a named reference point (AC1.1.3).

Three outcomes and never an empty answer (AC1.1.4): resolved, outside the
area SportAble covers, or unresolved with suggestions. A place the person did
give is never silently dropped; failing to resolve it is a 422.
"""

from dataclasses import dataclass

from app.core.errors import ApiError
from app.domain.presenters import reference_out
from app.repositories.protocols import LocationMatch, ReferencePoint, ReferenceRepository
from app.schemas.locations import CoverageOut, MatchedOut, ResolveOut, SuggestionOut
from app.services.inputs import PlaceInput

COVERAGE_DESCRIPTION = "SportAble covers sport venues across Victoria."
COVERAGE_EXAMPLES = ["Melbourne", "Darebin", "Geelong", "Ballarat", "Bendigo"]


def _did_you_mean(match: LocationMatch) -> str:
    """The suggestion clause of an unknown_place message, or an empty string."""
    labels = [s.label for s in match.suggestions[:3]]
    if not labels:
        return ""
    return " Did you mean " + ", ".join(labels) + "?"


def _kind(value: str | None) -> str:
    """Narrow a gazetteer kind to the two the contract names."""
    return "postcode" if value == "postcode" else "suburb"


@dataclass(frozen=True)
class LocationService:
    """Place resolution for every endpoint that measures a distance."""

    reference: ReferenceRepository

    def resolve_place(self, place: PlaceInput) -> ReferencePoint:
        """The point for a typed place, or the right 422 (unknown_place, outside_coverage)."""
        if place.point is not None:
            return place.point
        match = self.reference.resolve_location(place.suburb, place.postcode)
        if match.outcome == "resolved" and match.reference is not None:
            return match.reference
        typed = place.typed
        if match.outcome == "outside_coverage":
            raise ApiError(
                422,
                "outside_coverage",
                f"{match.matched_label or typed} is outside the area SportAble covers. "
                f"{COVERAGE_DESCRIPTION}",
            )
        raise ApiError(
            422,
            "unknown_place",
            f"No suburb or postcode matching {typed!r}.{_did_you_mean(match)}",
        )

    def resolve_optional(self, place: PlaceInput | None) -> ReferencePoint | None:
        """``resolve_place`` when a place was given, None when it was not."""
        if place is None or not place.given:
            return None
        return self.resolve_place(place)

    def resolve_query(self, place: PlaceInput, typed: str) -> ResolveOut:
        """``GET /locations/resolve``: one of three outcomes, never empty (AC1.1.4)."""
        if place.point is not None:
            return ResolveOut(
                outcome="resolved",
                query=typed,
                reference_point=reference_out(place.point),
                matched=MatchedOut(label=place.point.label, kind="point"),
            )
        match = self.reference.resolve_location(place.suburb, place.postcode)
        if match.outcome == "resolved" and match.reference is not None:
            return ResolveOut(
                outcome="resolved",
                query=typed,
                reference_point=reference_out(match.reference),
                matched=MatchedOut(
                    label=match.matched_label or typed, kind=_kind(match.reference.kind)
                ),
            )
        if match.outcome == "outside_coverage":
            return _outside_coverage_out(match, typed)
        return _unresolved_out(match, typed)


def _outside_coverage_out(match: LocationMatch, typed: str) -> ResolveOut:
    """The outside_coverage outcome, with the coverage description and examples."""
    label = match.matched_label or typed
    return ResolveOut(
        outcome="outside_coverage",
        query=typed,
        matched=MatchedOut(label=label, kind=_kind(match.matched_kind)),
        message=f"{label} is outside the area SportAble covers. {COVERAGE_DESCRIPTION}",
        coverage=CoverageOut(description=COVERAGE_DESCRIPTION, examples=COVERAGE_EXAMPLES),
    )


def _unresolved_out(match: LocationMatch, typed: str) -> ResolveOut:
    """The unresolved outcome, carrying whatever the gazetteer found similar."""
    return ResolveOut(
        outcome="unresolved",
        query=typed,
        message=f"We could not find a suburb or postcode matching {typed!r}.",
        suggestions=[
            SuggestionOut(label=s.label, kind=_kind(s.kind), code=s.code) for s in match.suggestions
        ],
    )

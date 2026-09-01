"""Fixture data for the SportAble API, drawn from the Iteration 1 acceptance criteria.

WHY THIS EXISTS
    The Frontend team cannot build against an API that does not exist yet, and
    the backend engineer cannot write one until the schema settles. These
    fixtures let both proceed in parallel: the shapes below are served from the
    real URL, through the real CloudFront and API Gateway path, with real
    latency — only the data is fabricated.

WHAT IT IS NOT
    Not a specification. This is a DRAFT contract inferred from the acceptance
    criteria in SportAble_Epics_UserStories_Iteration1.docx. The backend
    engineer owns the real one. Where this is wrong, the document wins.

THE RULES THESE SHAPES ENCODE
    Three of the product's non-negotiables are visible in the data model, and
    the frontend has to honour them:

    1. "Unknown is never a no." A facility with no record has status
       `no_published_information`, which is a THIRD state — not a falsy value.
       `if facility.confirmed` would silently render it as absent. (AC1.3.3)

    2. Every confirmed fact carries its provenance: measured distance, source
       name, and the date that source was last updated. (AC1.3.2, AC2.2.3)

    3. There is NO combined score, rating, percentage or star value anywhere,
       by design. A single number hides the one failed facility that decides
       whether a person can attend. (AC2.1.2)
"""

from __future__ import annotations

from typing import Any

# The four facilities named in AC1.2.1 and AC1.3.1. This list is closed.
FACILITY_TYPES = (
    "accessible_toilet",
    "accessible_parking",
    "step_free_transport_stop",
    "accessible_change_facility",
)

# The three states from section 2 of the requirements document.
STATUS_CONFIRMED = "confirmed"
STATUS_NOT_AVAILABLE = "not_available"
STATUS_NO_PUBLISHED_INFORMATION = "no_published_information"

# AC1.3.3 fixes this wording. It is not the frontend's to paraphrase.
NO_INFORMATION_MESSAGE = "No published information — check with the venue"


def _confirmed(kind: str, distance_m: int, source: str, updated: str) -> dict[str, Any]:
    """A facility a named source positively records, with its provenance."""
    return {
        "type": kind,
        "status": STATUS_CONFIRMED,
        "distance_m": distance_m,
        "source": {"name": source, "last_updated": updated},
    }


def _unknown(kind: str) -> dict[str, Any]:
    """The default state for most attributes. Never a no."""
    return {
        "type": kind,
        "status": STATUS_NO_PUBLISHED_INFORMATION,
        "message": NO_INFORMATION_MESSAGE,
    }


def _not_available(kind: str, source: str, updated: str) -> dict[str, Any]:
    """A source positively records the facility as absent. A fact, not a gap."""
    return {
        "type": kind,
        "status": STATUS_NOT_AVAILABLE,
        "source": {"name": source, "last_updated": updated},
    }


# AC1.1.1 — the sport field offers only sports that exist in the venue data.
SPORTS: dict[str, Any] = {
    "sports": [
        {"id": "basketball", "name": "Basketball", "venue_count": 38},
        {"id": "netball", "name": "Netball", "venue_count": 44},
        {"id": "swimming", "name": "Swimming", "venue_count": 21},
        {"id": "tennis", "name": "Tennis", "venue_count": 57},
        {"id": "australian-rules-football", "name": "Australian rules football", "venue_count": 66},
        {"id": "cricket", "name": "Cricket", "venue_count": 61},
        {"id": "lawn-bowls", "name": "Lawn bowls", "venue_count": 29},
    ]
}

_VENUES: list[dict[str, Any]] = [
    {
        "id": "vsr-10432",
        "name": "Preston City Oval",
        "suburb": "Preston",
        "postcode": "3072",
        "street_address": "121 Cramer Street, Preston VIC 3072",
        "sports": ["Australian rules football", "Cricket"],
        "distance_from_reference_m": 640,
        "facilities": [
            _confirmed("accessible_toilet", 45, "National Public Toilet Map", "2026-07-14"),
            _confirmed("accessible_parking", 120, "Darebin City Council", "2026-05-02"),
            _confirmed("step_free_transport_stop", 380, "PTV GTFS", "2026-08-19"),
            _unknown("accessible_change_facility"),
        ],
    },
    {
        "id": "vsr-11876",
        "name": "Northcote Aquatic and Recreation Centre",
        "suburb": "Northcote",
        "postcode": "3070",
        "street_address": "7 Mayer Park, Northcote VIC 3070",
        "sports": ["Swimming", "Basketball"],
        "distance_from_reference_m": 1820,
        "facilities": [
            _confirmed("accessible_toilet", 15, "National Public Toilet Map", "2026-07-14"),
            _confirmed(
                "accessible_change_facility", 15, "National Public Toilet Map", "2026-07-14"
            ),
            _confirmed("accessible_parking", 60, "Darebin City Council", "2026-05-02"),
            _confirmed("step_free_transport_stop", 210, "PTV GTFS", "2026-08-19"),
        ],
    },
    {
        "id": "vsr-10088",
        "name": "Reservoir Leisure Centre",
        "suburb": "Reservoir",
        "postcode": "3073",
        "street_address": "2 Cheddar Road, Reservoir VIC 3073",
        "sports": ["Swimming", "Netball"],
        "distance_from_reference_m": 2940,
        "facilities": [
            _confirmed("accessible_toilet", 30, "National Public Toilet Map", "2026-07-14"),
            _not_available("accessible_change_facility", "Darebin City Council", "2026-05-02"),
            _unknown("accessible_parking"),
            _confirmed("step_free_transport_stop", 540, "PTV GTFS", "2026-08-19"),
        ],
    },
]

# AC1.2.3 — venues with no published information for a filtered facility are
# GROUPED AND COUNTED, never silently removed. Removal is invisible: the user
# sees a shorter list and cannot tell whether the venues lack the facility or
# have simply never been documented.
_UNDOCUMENTED: list[dict[str, Any]] = [
    {
        "id": "vsr-12551",
        "name": "Coburg City Oval",
        "suburb": "Coburg",
        "postcode": "3058",
        "street_address": "Outlook Road, Coburg VIC 3058",
        "sports": ["Australian rules football", "Cricket"],
        "distance_from_reference_m": 3610,
        "facilities": [
            _unknown("accessible_toilet"),
            _unknown("accessible_parking"),
            _confirmed("step_free_transport_stop", 260, "PTV GTFS", "2026-08-19"),
            _unknown("accessible_change_facility"),
        ],
    },
]


def search_response() -> dict[str, Any]:
    """Fixture for GET /api/v1/venues/search.

    AC1.1.3 requires the reference point to be NAMED on screen, because a
    suburb is an area rather than a single point. It is a first-class field
    here rather than something the frontend composes.
    """
    return {
        "reference_point": {
            "label": "the centre of Preston 3072",
            "latitude": -37.7412,
            "longitude": 145.0006,
        },
        "distance_limit_m": 500,
        "counts": {
            "matching": len(_VENUES),
            "undocumented": len(_UNDOCUMENTED),
        },
        "results": _VENUES,
        "undocumented_group": {
            "label": "Venues with no published information for the facilities you filtered on",
            "count": len(_UNDOCUMENTED),
            "results": _UNDOCUMENTED,
        },
        "_fixture": True,
    }


def venue_response(venue_id: str) -> dict[str, Any] | None:
    """Fixture for GET /api/v1/venues/{id}.

    Adds what the card needs beyond a search result: AC2.1.3's inside-or-nearby
    distinction, AC2.1.4's opening hours and MLAK requirement, and AC2.1.5's
    section naming what the card cannot tell the user.
    """
    venue = next((v for v in _VENUES + _UNDOCUMENTED if v["id"] == venue_id), None)
    if venue is None:
        return None

    card = dict(venue)
    card["facility_detail"] = {
        "accessible_toilet": {
            # AC2.1.3 — inside the venue, a separate public facility nearby, or
            # plainly that no source records which.
            "location_relative_to_venue": "separate_public_facility_nearby",
            # AC2.1.4 — where the source records neither, say so rather than
            # leaving the field blank.
            "opening_hours": "6:00am - 9:00pm",
            "mlak_required": True,
        },
        "accessible_change_facility": {
            "location_relative_to_venue": "not_recorded",
            "opening_hours": None,
            "mlak_required": None,
        },
    }
    # AC2.1.5 — a clearly headed section naming what the card cannot tell you,
    # with a plain-English reason.
    card["limits"] = {
        "heading": "What this card cannot tell you",
        "items": [
            {
                "topic": "Step-free entry to the building",
                "reason": "No available dataset records it.",
            },
            {
                "topic": "Access to the playing surface itself",
                "reason": "No available dataset records it.",
            },
        ],
    }
    card["_fixture"] = True
    return card

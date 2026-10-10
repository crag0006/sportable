"""The assistant's tools (contract v0.3 section 8.7): definitions and executors.

Eight read-only tools, each a thin wrapper over an existing service, returning
a compact object that already carries every facility's ``message``, ``source``
and dates; plus ``final_answer``, the output tool. The model never sees SQL or
raw rows, and nothing here can write.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.facilities import KEY_TO_KIND, parse_needs
from app.repositories.protocols import ReferencePoint, ReferenceRepository
from app.schemas.common import FacilityOut
from app.schemas.events import EventOut
from app.services.assistant.retrieval import Retrieval
from app.services.events import EventService
from app.services.inputs import EventListQuery, PlaceInput, SearchQuery, VenuePageQuery
from app.services.locations import LocationService
from app.services.reference import ReferenceService
from app.services.venues import VenueService

FACILITY_ENUM = [
    "accessible_toilet",
    "accessible_parking",
    "accessible_transport_stop",
    "accessible_change_facility",
]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MAX_VENUES_PER_GROUP = 5
MAX_EVENTS = 8
_TRAILING_POSTCODE = re.compile(r"^(.*?)[\s,]*(\d{4})$")
_LAT_LON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _tool(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    """One Anthropic tool definition with a closed object schema."""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _nullable(kind: str, description: str = "") -> dict[str, Any]:
    """A JSON schema for ``kind | null``."""
    out: dict[str, Any] = {"type": [kind, "null"]}
    if description:
        out["description"] = description
    return out


TOOL_DEFS: list[dict[str, Any]] = [
    _tool(
        "resolve_location",
        "Turn a place the user typed (suburb, suburb + postcode, or postcode) into a named "
        "reference point. Call before search_venues or search_events whenever the user names a "
        "place. If outcome is 'unresolved', offer the suggestions instead of guessing.",
        {"query": {"type": "string", "description": "e.g. 'Preston', 'Preston 3072', '3072'"}},
        ["query"],
    ),
    _tool(
        "find_venue",
        "Find a venue by (part of) its name, optionally narrowed by a suburb. Returns up to 5 "
        "candidates with ids. Call this when the user names a venue, then call get_venue "
        "with the id.",
        {
            "name": {"type": "string"},
            "suburb": _nullable("string", "e.g. 'Heidelberg West', or null"),
        },
        ["name", "suburb"],
    ),
    _tool(
        "list_sports",
        "List the sports the site knows, optionally filtered by a partial name. Call when the "
        "sport is unclear or misspelt, or to confirm a sport exists before searching.",
        {"query": _nullable("string", "partial name, or null for all")},
        ["query"],
    ),
    _tool(
        "search_venues",
        "Find venues for one sport near one place. Returns venues in three groups (matched, "
        "undocumented, not_available) with the four access facilities evaluated at distance_m, "
        "each with status, source and date. Never state a facility status not in the result.",
        {
            "sport": {"type": "string"},
            "location": {"type": "string", "description": "as typed or as resolved"},
            "facilities": {
                "type": "array",
                "items": {"type": "string", "enum": FACILITY_ENUM},
                "description": "the user's access requirements; groups results, never hides any",
            },
            "distance_m": _nullable(
                "integer",
                "The FACILITY distance band (250, 500 or 1000 m): how close a public toilet, "
                "bay or station must be to the venue to count. It is NOT a venue search "
                "radius; venues up to "
                "10 km from the place are always returned. Null for the default 500.",
            ),
        },
        ["sport", "location", "facilities", "distance_m"],
    ),
    _tool(
        "get_venue",
        "One venue's full record: address, sports, the four facilities with details (opening "
        "hours, key required, changing places), each with source and date, the access chain and "
        "the count of upcoming events. Call for any question about a specific venue.",
        {"venue_id": {"type": "string"}, "distance_m": _nullable("integer")},
        ["venue_id", "distance_m"],
    ),
    _tool(
        "search_events",
        "Find sports events and weekly programs. Filters are optional; pass null for what the "
        "user did not say. venue_id lists what is on at one venue. Returns up to 8 events with the "
        "venue's access status, or a note when the venue is not in our register.",
        {
            "sport": _nullable("string"),
            "location": _nullable("string"),
            "venue_id": _nullable("string"),
            "date_from": _nullable("string", "YYYY-MM-DD"),
            "date_to": _nullable("string", "YYYY-MM-DD"),
            "weekday": {"type": ["string", "null"], "enum": [*WEEKDAYS, None]},
        },
        ["sport", "location", "venue_id", "date_from", "date_to", "weekday"],
    ),
    _tool(
        "get_event",
        "One event's record with its venue's access facilities, links, price, registration and "
        "its calendar block. Call when the user asks about a specific event or picks one "
        "for a calendar.",
        {"event_id": {"type": "string"}},
        ["event_id"],
    ),
    _tool(
        "search_program_descriptions",
        "Search the publishers' own program descriptions (what a program is, who it is for, "
        "what to bring, how to join). Call only for questions about program content that the "
        "structured fields do not answer. Returns up to 4 passages with the program id and "
        "source. If nothing is returned, say that the publisher did not describe it.",
        {
            "question": {
                "type": "string",
                "description": "A full natural-language sentence, close to the user's own words "
                "(e.g. 'Which programs mention audible tennis balls?'). Not a keyword list.",
            }
        },
        ["question"],
    ),
]

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "venue",
                "event",
                "search_venues",
                "search_events",
                "directions",
                "calendar_add",
            ],
        },
        "venue_id": _nullable("string"),
        "event_id": _nullable("string"),
        "event_ids": {"type": ["array", "null"], "items": {"type": "string"}},
        "sport": _nullable("string"),
        "location": _nullable("string"),
        "facilities": {
            "type": ["array", "null"],
            "items": {"type": "string", "enum": FACILITY_ENUM},
        },
        "distance_m": _nullable("integer"),
        "weekday": _nullable("string"),
        "from": _nullable("string", "starting point for directions"),
    },
    "required": [
        "kind",
        "venue_id",
        "event_id",
        "event_ids",
        "sport",
        "location",
        "facilities",
        "distance_m",
        "weekday",
        "from",
    ],
    "additionalProperties": False,
}

FINAL_TOOL: dict[str, Any] = _tool(
    "final_answer",
    "Call this exactly once when you are ready to answer. Put the answer text in `answer` with "
    "no URLs in it. Name the venues and events you refer to by id. Use `actions` for pages the "
    "user may want to open; the site builds the links.",
    {
        "kind": {
            "type": "string",
            "enum": ["answer", "results", "clarify", "no_information", "capability"],
            "description": "answer: a factual answer; results: a list of venues or events; "
            "clarify: "
            "you need one more detail; no_information: the subject exists but nothing is published "
            "for the detail asked; capability: out of scope",
        },
        "answer": {
            "type": "string",
            "description": "Plain English, no URLs, no markdown headings.",
        },
        "venue_ids": {"type": "array", "items": {"type": "string"}},
        "event_ids": {"type": "array", "items": {"type": "string"}},
        "actions": {"type": "array", "items": ACTION_SCHEMA},
        "suggested_questions": {"type": "array", "items": {"type": "string"}},
    },
    ["kind", "answer", "venue_ids", "event_ids", "actions", "suggested_questions"],
)


# ---------------------------------------------------------------- compaction
def facility_compact(f: FacilityOut) -> dict[str, Any]:
    """The compact tile: type, display, distance, message, source name and date, key details."""
    out: dict[str, Any] = {
        "type": f.type,
        "display": f.display,
        "distance_m": f.distance_m,
        "message": f.message,
        "source": {"name": f.source.name, "publisher_last_updated": f.source.publisher_last_updated}
        if f.source
        else None,
    }
    if f.detail is not None:
        d = f.detail
        out["detail"] = {
            "location_relative_to_venue": d.location_relative_to_venue,
            "opening_hours": d.opening_hours,
            "opening_hours_unrecorded": d.opening_hours_unrecorded,
            "key_required": d.key_required,
            "key_requirement_unrecorded": d.key_requirement_unrecorded,
            "changing_places": d.changing_places,
            "has_shower": d.has_shower,
        }
    if f.alternative is not None:
        out["alternative"] = {"name": f.alternative.name, "distance_m": f.alternative.distance_m}
    return out


def event_compact(e: EventOut) -> dict[str, Any]:
    """One event as the model should see it (and as the panel's card)."""
    rec = e.recurrence
    return {
        "id": e.id,
        "kind": e.kind,
        "title": e.title,
        "sport": e.sport or e.sport_raw,
        "when": rec.summary if rec else " ".join(p for p in (e.date_local, e.time_local) if p),
        "weekdays": list(rec.weekdays) if rec else [],
        "time_of_day": list(rec.time_of_day) if rec else [],
        "price": e.price,
        "venue": {
            "id": e.venue.venue_id,
            "name": e.venue.name,
            "suburb": e.venue.suburb,
            "matched": e.venue.matched,
            "message": e.venue.message,
        },
        "distance_m": e.distance_m,
        "facilities": [facility_compact(f) for f in e.access.facilities],
        "href": e.links.detail,
        "external": e.links.external,
        "registration": e.links.registration,
    }


def place_input(text: str) -> PlaceInput:
    """A typed place as the services take it: ``lat,lon`` or suburb with an optional postcode."""
    m = _LAT_LON.match(text)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return PlaceInput(point=ReferencePoint("your starting point", lat, lon, kind="point"))
    suburb: str | None = text.strip()
    postcode: str | None = None
    tail = _TRAILING_POSTCODE.match(suburb or "")
    if tail:
        suburb, postcode = tail.group(1).strip() or None, tail.group(2)
    if suburb is None and postcode is None:
        return PlaceInput()
    return PlaceInput(suburb=suburb, postcode=postcode)


def _clean(args: dict[str, Any]) -> dict[str, Any]:
    """Treat the strings "null" and "none" as absent: some models emit them for empty slots."""
    return {
        k: (None if isinstance(v, str) and v.strip().lower() in ("null", "none", "") else v)
        for k, v in args.items()
    }


@dataclass(frozen=True)
class ToolRunner:
    """Executes one tool call over the services; every result is a plain dict."""

    venues: VenueService
    events: EventService
    locations: LocationService
    references: ReferenceService
    reference_repo: ReferenceRepository
    retrieval: Retrieval | None
    settings: Settings
    now: datetime

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """The tool's compact result, or ``{"error": code, "message": ...}``; never raises."""
        handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "resolve_location": self.resolve_location,
            "find_venue": self.find_venue,
            "list_sports": self.list_sports,
            "search_venues": self.search_venues,
            "get_venue": self.get_venue,
            "search_events": self.search_events,
            "get_event": self.get_event,
            "search_program_descriptions": self.search_program_descriptions,
        }
        handler = handlers.get(name)
        if handler is None:
            return {"error": "unknown_tool", "message": name}
        try:
            return handler(**_clean(args))
        except ApiError as exc:
            return {"error": exc.code, "message": exc.message}
        except TypeError as exc:
            return {"error": "bad_arguments", "message": str(exc)}

    def resolve_location(self, query: str) -> dict[str, Any]:
        """``/locations/resolve`` compacted; ``location`` is what the other tools accept."""
        r = self.locations.resolve_query(place_input(query), query.strip())
        return {
            "outcome": r.outcome,
            "label": r.reference_point.label
            if r.reference_point
            else (r.matched.label if r.matched else None),
            "kind": r.matched.kind if r.matched else None,
            "location": query.strip() if r.outcome == "resolved" else None,
            "message": r.message,
            "suggestions": [s.label for s in r.suggestions][:5],
        }

    def find_venue(self, name: str, suburb: str | None) -> dict[str, Any]:
        """Venue candidates by name."""
        rows = self.reference_repo.find_venues(name, suburb)
        return {
            "candidates": [
                {
                    "id": v.venue_id,
                    "name": v.name,
                    "suburb": v.suburb,
                    "postcode": v.postcode,
                    "href": f"/venues/{v.venue_id}",
                }
                for v in rows
            ]
        }

    def list_sports(self, query: str | None) -> dict[str, Any]:
        """``/sports?q=`` at most 30 names."""
        rows = self.references.sports(query).sports
        return {"sports": [s.model_dump() for s in rows[:30]], "total": len(rows)}

    def search_venues(
        self, sport: str, location: str, facilities: list[str] | None, distance_m: int | None
    ) -> dict[str, Any]:
        """``/venues/search`` in three groups, capped."""
        cfg = self.settings.search
        band = distance_m if distance_m in cfg.distance_bands_m else cfg.default_distance_m
        kinds = [KEY_TO_KIND[k] for k in parse_needs(facilities or [])]
        out = self.venues.search(
            SearchQuery(sport=sport, place=place_input(location), kinds=kinds, limit_m=band)
        )

        def group(rows: list[Any]) -> list[dict[str, Any]]:
            """The first few venues of a group as compact cards."""
            return [
                {
                    "id": v.id,
                    "name": v.name,
                    "suburb": v.suburb,
                    "distance_m": v.distance_m,
                    "href": v.href,
                    "facilities": [facility_compact(f) for f in v.facilities],
                }
                for v in rows[:MAX_VENUES_PER_GROUP]
            ]

        return {
            "place": out.reference_point.label,
            "distance_limit_m": out.distance_limit_m,
            "counts": out.counts.model_dump(),
            "matched": group(out.results),
            "undocumented": {
                "label": out.undocumented_group.label,
                "venues": group(out.undocumented_group.results),
            },
            "not_available": {
                "label": out.not_available_group.label,
                "venues": group(out.not_available_group.results),
            },
            "note": "Distances are straight-line metres from the place named above.",
        }

    def get_venue(self, venue_id: str, distance_m: int | None) -> dict[str, Any]:
        """``/venues/{id}`` compacted with detail rows and the access chain."""
        cfg = self.settings.search
        band = distance_m if distance_m in cfg.distance_bands_m else cfg.default_distance_m
        card = self.venues.page(
            VenuePageQuery(venue_id=venue_id, origin=None, limit_m=band), self.now
        )
        return {
            "id": card.id,
            "name": card.name,
            "address": card.address,
            "suburb": card.suburb,
            "lga": card.lga,
            "sports": card.sports,
            "href": card.href,
            "facilities": [facility_compact(f) for f in card.facilities],
            "access_chain": [
                {"link": c.link, "status": c.status, "summary": c.summary}
                for c in card.access_chain
            ],
            "limits": [i.topic for i in card.limits.items],
            "upcoming_events": card.upcoming_events.model_dump(exclude_none=True),
            "last_updated": card.last_updated,
        }

    def search_events(
        self,
        sport: str | None,
        location: str | None,
        venue_id: str | None,
        date_from: str | None,
        date_to: str | None,
        weekday: str | None,
    ) -> dict[str, Any]:
        """``/events`` up to 8 events compacted."""
        today = self.now.date()
        start = datetime.fromisoformat(date_from).date() if date_from else today
        end = (
            datetime.fromisoformat(date_to).date()
            if date_to
            else start + timedelta(days=self.settings.events.default_window_days)
        )
        query = EventListQuery(
            date_from=start,
            date_to=end,
            place=place_input(location) if location else None,
            within_m=10_000,
            sports=(sport,) if sport else (),
            venue_id=venue_id,
            weekdays=(weekday.lower(),) if weekday else (),
            limit_m=self.settings.search.default_distance_m,
            page_size=MAX_EVENTS,
        )
        out = self.events.list(query, self.now)
        return {
            "window": {"from": out.window.from_, "to": out.window.to},
            "total": out.counts.total,
            "unmatched_venue": out.counts.unmatched_venue,
            "events": [event_compact(e) for e in out.events[:MAX_EVENTS]],
            "empty_message": out.empty_message,
            "attribution": out.attribution,
        }

    def get_event(self, event_id: str) -> dict[str, Any]:
        """``/events/{id}`` compacted, with the description and the calendar block."""
        e = self.events.detail(event_id, self.settings.search.default_distance_m, self.now)
        out = event_compact(e)
        out["description"] = (e.description or "")[:1200]
        out["organisation"] = e.organisation
        out["age_ranges"] = e.age_ranges
        out["access_needs"] = e.access_needs
        out["share_url"] = e.share.url
        calendar = getattr(e, "calendar", None)  # lands with the calendar block (section 7.7)
        out["calendar"] = calendar.model_dump(exclude_none=True) if calendar else None
        return out

    def search_program_descriptions(self, question: str) -> dict[str, Any]:
        """Hybrid retrieval over the descriptions, or an honest "not configured"."""
        if self.retrieval is None:
            return {"available": False, "note": "Retrieval is not configured in this environment."}
        passages = self.retrieval.search(question)
        return {
            "available": True,
            "passages": [
                {
                    "program_id": p.program_id,
                    "title": p.title,
                    "text": p.text,
                    "source_id": p.source_id,
                    "publisher_page": p.publisher_page,
                    "similarity": p.similarity,
                    "href": p.href,
                }
                for p in passages
            ],
            "note": "Passages are the publisher's own words about a program; quote them as such.",
        }

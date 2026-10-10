"""The seven tools: OpenAI function schemas plus executors over the running API.

Six tools are HTTP calls to the local SportAble API and return a compact JSON
object (ASSISTANT_TOOL_PROTOCOL section B.2). The seventh embeds the question
on the embedding server and searches program_description_chunk in the local
database; it reports itself unavailable until both exist.
"""

import json
from typing import Any

import httpx

from lab import config

FACILITY_ENUM = [
    "accessible_toilet",
    "accessible_parking",
    "accessible_transport_stop",
    "accessible_change_facility",
]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MAX_VENUES = 5
MAX_EVENTS = 8


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """One OpenAI-format tool definition with a closed object schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOLS: list[dict] = [
    _schema(
        "resolve_location",
        "Turn a place the user typed (suburb, suburb + postcode, or postcode) into a named "
        "reference point. Call before search_venues or search_events whenever the user names a "
        "place. If outcome is 'unresolved', offer the suggestions instead of guessing.",
        {"query": {"type": "string", "description": "e.g. 'Preston', 'Preston 3072', '3072'"}},
        ["query"],
    ),
    _schema(
        "find_venue",
        "Find a venue by (part of) its name, optionally narrowed by a suburb. Returns up to 5 "
        "candidates with ids. Call this when the user names a venue, then call get_venue with the id.",
        {
            "name": {"type": "string", "description": "e.g. 'Olympic Leisure Centre'"},
            "suburb": {
                "type": ["string", "null"],
                "description": "e.g. 'Heidelberg West', or null",
            },
        },
        ["name", "suburb"],
    ),
    _schema(
        "list_sports",
        "List the sports the site knows, optionally filtered by a partial name. Call when the "
        "sport is unclear or misspelt, or to confirm a sport exists before searching.",
        {"query": {"type": ["string", "null"], "description": "partial name, or null for all"}},
        ["query"],
    ),
    _schema(
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
            "distance_m": {
                "type": ["integer", "null"],
                "description": "The FACILITY distance band (250, 500 or 1000 m): how close a public "
                "toilet, bay or station must be to the venue to count. It is NOT a venue search "
                "radius; venues up to 10 km from the place are always returned. Null for the default 500.",
            },
        },
        ["sport", "location", "facilities", "distance_m"],
    ),
    _schema(
        "get_venue",
        "One venue's full record: address, sports, the four facilities with details (opening "
        "hours, key required, changing places), each with source and date, the access chain and "
        "the count of upcoming events. Call for any question about a specific venue.",
        {"venue_id": {"type": "string"}, "distance_m": {"type": ["integer", "null"]}},
        ["venue_id", "distance_m"],
    ),
    _schema(
        "search_events",
        "Find sports events and weekly programs. Filters are optional; pass null for what the "
        "user did not say. Returns up to 8 events with the venue's access status, or a note when "
        "the venue is not in our register.",
        {
            "sport": {"type": ["string", "null"]},
            "location": {"type": ["string", "null"]},
            "date_from": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
            "date_to": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
            "weekday": {"type": ["string", "null"], "enum": [*WEEKDAYS, None]},
        },
        ["sport", "location", "date_from", "date_to", "weekday"],
    ),
    _schema(
        "get_event",
        "One event's record with its venue's access facilities and links.",
        {"event_id": {"type": "string"}},
        ["event_id"],
    ),
    _schema(
        "search_program_descriptions",
        "Search the publishers' own program descriptions (what a program is, who it is for, "
        "what to bring, how to join). Call only for questions about program content that the "
        "structured fields do not answer. Returns up to 4 passages with the program id and "
        "source. If nothing is returned, say that the publisher did not describe it.",
        {
            "question": {
                "type": "string",
                "description": "A full natural-language sentence, close to the user's own words "
                "(e.g. 'Which programs mention audible tennis balls?'). Not a keyword list: "
                "short keyword queries score poorly.",
            }
        },
        ["question"],
    ),
]


# The model ends every turn by calling this. It names ids and intents; the
# builder (lab.builder) turns them into links, cards and sources. No URL field
# exists anywhere in this schema on purpose.
FINAL_TOOL = _schema(
    "final_answer",
    "Call this exactly once when you are ready to answer. Put the answer text in `answer` "
    "with no URLs in it. Name the venues and events you refer to by id. Use `actions` for "
    "pages the user may want to open; the site builds the links.",
    {
        "kind": {
            "type": "string",
            "enum": ["answer", "results", "clarify", "no_information", "capability"],
            "description": "answer: a factual answer; results: a list of venues or events; clarify: you "
            "need one more detail; no_information: the subject exists but nothing is published for "
            "the detail asked; capability: out of scope",
        },
        "answer": {
            "type": "string",
            "description": "Plain English, no URLs, no markdown headings.",
        },
        "venue_ids": {"type": "array", "items": {"type": "string"}},
        "event_ids": {"type": "array", "items": {"type": "string"}},
        "actions": {
            "type": "array",
            "description": "Pages worth opening, in order. Only ids and searches that appeared"
            " in this conversation's tool results.",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["venue", "event", "search_venues", "search_events", "directions"],
                    },
                    "venue_id": {"type": ["string", "null"]},
                    "event_id": {"type": ["string", "null"]},
                    "sport": {"type": ["string", "null"]},
                    "location": {"type": ["string", "null"]},
                    "facilities": {
                        "type": ["array", "null"],
                        "items": {"type": "string", "enum": FACILITY_ENUM},
                    },
                    "distance_m": {"type": ["integer", "null"]},
                    "weekday": {"type": ["string", "null"]},
                    "from": {
                        "type": ["string", "null"],
                        "description": "starting point for directions",
                    },
                },
                "required": [
                    "kind",
                    "venue_id",
                    "event_id",
                    "sport",
                    "location",
                    "facilities",
                    "distance_m",
                    "weekday",
                    "from",
                ],
                "additionalProperties": False,
            },
        },
        "suggested_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Up to 3 short follow-ups.",
        },
    },
    ["kind", "answer", "venue_ids", "event_ids", "actions", "suggested_questions"],
)


# ----------------------------------------------------------------- helpers
def _get(path: str, params: dict[str, Any] | None = None) -> dict | None:
    """GET the API; an error envelope comes back as {"error": ...}."""
    clean = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
    r = httpx.get(f"{config.API_BASE}{path}", params=clean, timeout=20)
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        return {"error": err.get("code", f"http_{r.status_code}"), "message": err.get("message")}
    return r.json()


def _facility(f: dict) -> dict:
    """The compact tile: type, display, distance, message, source name and date."""
    src = f.get("source") or {}
    out = {
        "type": f["type"],
        "display": f["display"],
        "distance_m": f.get("distance_m"),
        "message": f["message"],
        "source": {
            "name": src.get("name"),
            "publisher_last_updated": src.get("publisher_last_updated"),
        }
        if src
        else None,
    }
    detail = f.get("detail")
    if detail:
        out["detail"] = {
            k: detail.get(k)
            for k in (
                "location_relative_to_venue",
                "opening_hours",
                "opening_hours_unrecorded",
                "key_required",
                "key_requirement_unrecorded",
                "changing_places",
                "has_shower",
            )
        }
    alt = f.get("alternative")
    if alt:
        out["alternative"] = {"name": alt.get("name"), "distance_m": alt.get("distance_m")}
    return out


def _venue_compact(v: dict) -> dict:
    """One search result as the model should see it."""
    return {
        "id": v["id"],
        "name": v["name"],
        "suburb": v.get("suburb"),
        "distance_m": v.get("distance_m"),
        "href": v["href"],
        "facilities": [_facility(f) for f in v["facilities"]],
    }


def _event_compact(e: dict) -> dict:
    """One event as the model should see it."""
    venue = e["venue"]
    rec = e.get("recurrence") or {}
    return {
        "id": e["id"],
        "kind": e["kind"],
        "title": e["title"],
        "sport": e.get("sport") or e.get("sport_raw"),
        "when": rec.get("summary") or " ".join(p for p in (e.get("date_local"), e.get("time_local")) if p),
        "weekdays": rec.get("weekdays", []),
        "time_of_day": rec.get("time_of_day", []),
        "price": e.get("price"),
        "venue": {
            "id": venue.get("venue_id"),
            "name": venue.get("name"),
            "suburb": venue.get("suburb"),
            "matched": venue["matched"],
            "message": venue.get("message"),
        },
        "distance_m": e.get("distance_m"),
        "facilities": [_facility(f) for f in e["access"]["facilities"]],
        "href": e["links"]["detail"],
        "external": e["links"]["external"],
    }


# --------------------------------------------------------------- executors
def resolve_location(query: str) -> dict:
    """GET /locations/resolve, compacted."""
    r = _get("/locations/resolve", {"q": query})
    if r is None or "error" in r:
        return r or {"error": "no_response"}
    ref = r.get("reference_point") or {}
    return {
        "outcome": r["outcome"],
        "label": ref.get("label") or (r.get("matched") or {}).get("label"),
        "kind": (r.get("matched") or {}).get("kind"),
        # What the other tools accept as `location`: the text as resolved.
        "location": r["query"] if r["outcome"] == "resolved" else None,
        "message": r.get("message"),
        "suggestions": [s["label"] for s in r.get("suggestions", [])][:5],
    }


SQL_FIND_VENUE = """
SELECT venue_id, name, suburb_name, postcode,
       similarity(lower(name), lower(%(q)s)) AS score
  FROM venue_card
 WHERE (lower(name) LIKE '%%' || lower(%(q)s) || '%%' OR similarity(lower(name), lower(%(q)s)) > 0.3)
   AND (%(suburb)s::text IS NULL OR lower(suburb_name) = lower(%(suburb)s)
        OR similarity(lower(suburb_name), lower(%(suburb)s)) > 0.4)
 ORDER BY score DESC, name
 LIMIT 5
"""


def find_venue(name: str, suburb: str | None) -> dict:
    """Venue candidates by name (trigram over venue_card).

    LAB ONLY: there is no API route for this yet. v0.3 needs one
    (GET /venues?q=name) or an AssistantRepository method; the gap is real.
    """
    import psycopg

    with psycopg.connect(config.require("DATABASE_URL")) as conn:
        rows = conn.execute(SQL_FIND_VENUE, {"q": name, "suburb": suburb}).fetchall()
    return {
        "candidates": [
            {"id": r[0], "name": r[1], "suburb": r[2], "postcode": r[3], "href": f"/venues/{r[0]}"} for r in rows
        ]
    }


def list_sports(query: str | None) -> dict:
    """GET /sports?q=, at most 30 names."""
    r = _get("/sports", {"q": query})
    if r is None or "error" in r:
        return r or {"error": "no_response"}
    return {"sports": r["sports"][:30], "total": len(r["sports"])}


def search_venues(sport: str, location: str, facilities: list[str], distance_m: int | None) -> dict:
    """GET /venues/search, three groups, capped."""
    r = _get(
        "/venues/search",
        {
            "sport": sport,
            "suburb": location,
            "facilities": ",".join(facilities),
            "distance_m": distance_m,
        },
    )
    if r is None or "error" in r:
        return r or {"error": "no_response"}
    return {
        "place": r["reference_point"]["label"],
        "distance_limit_m": r["distance_limit_m"],
        "counts": r["counts"],
        "matched": [_venue_compact(v) for v in r["results"][:MAX_VENUES]],
        "undocumented": {
            "label": r["undocumented_group"]["label"],
            "venues": [_venue_compact(v) for v in r["undocumented_group"]["results"][:MAX_VENUES]],
        },
        "not_available": {
            "label": r["not_available_group"]["label"],
            "venues": [_venue_compact(v) for v in r["not_available_group"]["results"][:MAX_VENUES]],
        },
        "note": "Distances are straight-line metres from the place named above.",
    }


def get_venue(venue_id: str, distance_m: int | None) -> dict:
    """GET /venues/{id}, the card compacted with detail rows."""
    r = _get(f"/venues/{venue_id}", {"distance_m": distance_m})
    if r is None or "error" in r:
        return r or {"error": "no_response"}
    return {
        "id": r["id"],
        "name": r["name"],
        "address": r.get("address"),
        "suburb": r.get("suburb"),
        "lga": r.get("lga"),
        "sports": r.get("sports", []),
        "href": r["href"],
        "facilities": [_facility(f) for f in r["facilities"]],
        "access_chain": [
            {"link": c["link"], "status": c["status"], "summary": c["summary"]} for c in r["access_chain"]
        ],
        "limits": [i["topic"] for i in r["limits"]["items"]],
        "upcoming_events": r["upcoming_events"],
        "last_updated": r.get("last_updated"),
    }


def search_events(
    sport: str | None,
    location: str | None,
    date_from: str | None,
    date_to: str | None,
    weekday: str | None,
) -> dict:
    """GET /events, up to 8 events compacted."""
    r = _get(
        "/events",
        {
            "sport": sport,
            "suburb": location,
            "from": date_from,
            "to": date_to,
            "weekday": weekday,
            "page_size": MAX_EVENTS,
        },
    )
    if r is None or "error" in r:
        return r or {"error": "no_response"}
    return {
        "window": {"from": r["window"]["from"], "to": r["window"]["to"]},
        "total": r["counts"]["total"],
        "unmatched_venue": r["counts"]["unmatched_venue"],
        "events": [_event_compact(e) for e in r["events"][:MAX_EVENTS]],
        "empty_message": r.get("empty_message"),
        "attribution": r.get("attribution", []),
    }


def get_event(event_id: str) -> dict:
    """GET /events/{id}, compacted, with the description text."""
    r = _get(f"/events/{event_id}")
    if r is None or "error" in r:
        return r or {"error": "no_response"}
    out = _event_compact(r)
    out["description"] = (r.get("description") or "")[:1200]
    out["organisation"] = r.get("organisation")
    out["age_ranges"] = r.get("age_ranges", [])
    out["access_needs"] = r.get("access_needs", [])
    out["registration"] = r["links"].get("registration")
    out["share_url"] = r["share"]["url"]
    return out


def search_program_descriptions(question: str) -> dict:
    """Embed the question, cosine search program_description_chunk, join the program."""
    if not config.EMBED_BASE:
        return {
            "available": False,
            "note": "Retrieval is not configured in this lab (EMBED_BASE unset).",
        }
    from lab.retrieval import search_chunks  # local import: psycopg only when needed

    return search_chunks(question)


EXECUTORS = {
    "resolve_location": resolve_location,
    "find_venue": find_venue,
    "list_sports": list_sports,
    "search_venues": search_venues,
    "get_venue": get_venue,
    "search_events": search_events,
    "get_event": get_event,
    "search_program_descriptions": search_program_descriptions,
}


def run_tool(name: str, arguments: str) -> str:
    """Execute one tool call and return the JSON the model will read."""
    fn = EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": "unknown_tool", "message": name})
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return json.dumps({"error": "bad_arguments", "message": str(exc)})
    # The GGUF model sometimes emits the STRING "null" for an empty slot.
    args = {
        k: (None if isinstance(v, str) and v.strip().lower() in ("null", "none", "") else v) for k, v in args.items()
    }
    try:
        return json.dumps(fn(**args), ensure_ascii=False)
    except TypeError as exc:
        return json.dumps({"error": "bad_arguments", "message": str(exc)})
    except httpx.HTTPError as exc:
        return json.dumps({"error": "api_unreachable", "message": str(exc)})

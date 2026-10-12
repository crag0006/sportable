"""Turn the model's final_answer plus the tool results into the response the frontend gets.

The model names ids and intents. Everything a user can click, every source line
and the whole "what I checked" trace are produced here from the tool payloads,
so nothing the model wrote can become a link, a source or a step. Any URL left
in the answer text that no tool returned is removed.
"""

import json
import re
from typing import Any
from urllib.parse import urlencode

URL_IN_TEXT = re.compile(r"(?:https?://[^\s)\]>\"']+|/(?:venues|events|api)[A-Za-z0-9:_/?=&%.-]*)")
NOTICE = "This conversation is not stored."
FACILITY_LABEL = {
    "accessible_toilet": "accessible toilet",
    "accessible_parking": "accessible parking",
    "accessible_transport_stop": "step-free railway station",
    "accessible_change_facility": "accessible change facility",
}


# ------------------------------------------------------------------ parsing
def _calls(tool_calls: list[str], payloads: list[str]) -> list[dict]:
    """``[{name, args, result}]`` from the loop's parallel lists (passive retrieval included)."""
    out = []
    for call, payload in zip(tool_calls, payloads, strict=False):
        if call.startswith("[passive]"):
            name, args = "search_program_descriptions", {"question": "(the user's message)"}
        else:
            name, raw = call.split("(", 1)
            try:
                args = json.loads(raw[:-1]) if raw.endswith(")") else json.loads(raw)
            except json.JSONDecodeError:
                args = {}
        try:
            result = json.loads(payload)
        except json.JSONDecodeError:
            result = {}
        out.append({"name": name, "args": args, "result": result})
    return out


def _walk(node: Any):
    """Every dict inside a JSON value, depth first."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# ---------------------------------------------------------------- whitelist
def seen_links(calls: list[dict]) -> set[str]:
    """Every href, external or publisher page any tool returned."""
    links: set[str] = set()
    for c in calls:
        for d in _walk(c["result"]):
            for key in ("href", "external", "publisher_page", "registration", "share_url"):
                if isinstance(d.get(key), str) and d[key]:
                    links.add(d[key])
    return links


def seen_venues(calls: list[dict]) -> dict[str, dict]:
    """Venue objects by id from search_venues, get_venue and find_venue results."""
    out: dict[str, dict] = {}
    for c in calls:
        for d in _walk(c["result"]):
            if "id" in d and isinstance(d.get("href"), str) and d["href"].startswith("/venues/") and "name" in d:
                out.setdefault(d["id"], d)
            elif d.get("matched") is True and d.get("id") and d.get("name") and "href" not in d:
                # The matched venue inside an event record: openable too.
                out.setdefault(
                    d["id"],
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "suburb": d.get("suburb"),
                        "href": f"/venues/{d['id']}",
                        "from_event": True,
                    },
                )
    return out


def seen_events(calls: list[dict]) -> dict[str, dict]:
    """Event objects by id from search_events and get_event results."""
    out: dict[str, dict] = {}
    for c in calls:
        for d in _walk(c["result"]):
            if "id" in d and isinstance(d.get("href"), str) and d["href"].startswith("/events/") and "title" in d:
                out.setdefault(d["id"], d)
            elif "program_id" in d and isinstance(d.get("href"), str) and d["href"].startswith("/events/"):
                # A retrieved passage names a program the user may open too.
                out.setdefault(
                    d["program_id"],
                    {
                        "id": d["program_id"],
                        "title": d.get("title") or d["program_id"],
                        "href": d["href"],
                        "from_passage": True,
                    },
                )
    return out


def scrub(answer: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Remove every URL or path in the text that no tool returned; report what was removed."""
    removed: list[str] = []

    def keep_or_drop(m: re.Match) -> str:
        link = m.group(0).rstrip(".,;:)")
        if link in allowed:
            return m.group(0)
        removed.append(link)
        return ""

    text = URL_IN_TEXT.sub(keep_or_drop, answer)
    text = re.sub(r"[ \t]*(?:Page|Pages|Full list|Links?|Venue page|Details)\s*:\s*(?=\n|$)", "", text)
    return re.sub(r"[ \t]+\n", "\n", text).strip(), removed


# ------------------------------------------------------------------ actions
def _search_href(kind: str, a: dict) -> str:
    """The SPA search page for a validated search action."""
    if kind == "search_venues":
        q = {
            "sport": a.get("sport"),
            "suburb": a.get("location"),
            "facilities": ",".join(a.get("facilities") or []) or None,
            "distance_m": a.get("distance_m"),
        }
        return "/venues?" + urlencode({k: v for k, v in q.items() if v})
    q = {"sport": a.get("sport"), "suburb": a.get("location"), "weekday": a.get("weekday")}
    return "/events?" + urlencode({k: v for k, v in q.items() if v})


def _ran_search(calls: list[dict], kind: str, a: dict) -> dict | None:
    """The tool call this search action repeats, or None when no such search was run."""
    tool = "search_venues" if kind == "search_venues" else "search_events"
    for c in calls:
        if c["name"] != tool or "error" in c["result"]:
            continue
        args = c["args"]
        if (args.get("sport") or "").lower() == (a.get("sport") or "").lower() and (
            args.get("location") or ""
        ).lower() == (a.get("location") or "").lower():
            return c
    return None


def build_links(actions: list[dict], calls: list[dict], venues: dict, events: dict) -> tuple[list[dict], list[dict]]:
    """Validated actions as links with labels; the rejected ones with the reason."""
    links: list[dict] = []
    dropped: list[dict] = []
    for a in actions or []:
        kind = a.get("kind")
        if kind == "venue" and a.get("venue_id") in venues:
            v = venues[a["venue_id"]]
            links.append({"kind": "venue", "label": f"Open {v['name']}", "href": v["href"]})
        elif kind == "event" and a.get("event_id") in events:
            e = events[a["event_id"]]
            links.append({"kind": "event", "label": f"Open {e['title']}", "href": e["href"]})
        elif kind in ("search_venues", "search_events") and (c := _ran_search(calls, kind, a)):
            total = c["result"].get("counts", {}).get("total_for_sport") or c["result"].get("total")
            what = f"{a.get('sport') or 'all'} {'venues' if kind == 'search_venues' else 'events'}"
            where = f" near {a.get('location')}" if a.get("location") else ""
            links.append(
                {
                    "kind": "search",
                    "label": f"See all {total} {what}{where}" if total else f"See {what}{where}",
                    "href": _search_href(kind, a),
                }
            )
        elif kind == "directions" and a.get("venue_id") in venues and a.get("from"):
            v = venues[a["venue_id"]]
            links.append(
                {
                    "kind": "directions",
                    "label": f"Directions to {v['name']}",
                    "href": f"/venues/{a['venue_id']}/directions?" + urlencode({"from": a["from"]}),
                }
            )
        else:
            dropped.append({"action": a, "reason": "not backed by a tool result in this turn"})
    seen: set[str] = set()
    unique = [link for link in links if not (link["href"] in seen or seen.add(link["href"]))]
    return unique, dropped


def event_links(events: list[dict]) -> list[dict]:
    """Registration and publisher-page buttons for the event cards in the answer.

    These come straight from the event records, so the model never has to
    repeat a URL; the answer text can say "registration is through the club's
    page" and the button carries it.
    """
    out: list[dict] = []
    for e in events:
        if e.get("registration"):
            out.append(
                {
                    "kind": "registration",
                    "label": f"Register for {e['title']}",
                    "href": e["registration"],
                }
            )
        if e.get("external"):
            out.append(
                {
                    "kind": "publisher",
                    "label": f"View {e['title']} on AAA Play",
                    "href": e["external"],
                }
            )
    return out


# ------------------------------------------------------------------- trace
def _summary(c: dict) -> tuple[str, str | None]:
    """One sentence per tool call, written from the call and its result, plus an optional href."""
    n, a, r = c["name"], c["args"], c["result"]
    if "error" in r:
        return f"{n} returned {r['error']}: {r.get('message') or ''}".strip(), None
    if n == "resolve_location":
        if r.get("outcome") == "resolved":
            return f'Resolved "{a.get("query")}" to {r.get("label")}.', None
        sugg = ", ".join(r.get("suggestions") or []) or "none"
        return (
            f'Could not resolve "{a.get("query")}" ({r.get("outcome")}); suggestions: {sugg}.',
            None,
        )
    if n == "find_venue":
        return (
            f'Looked up venues named "{a.get("name")}": {len(r.get("candidates", []))} candidate(s).',
            None,
        )
    if n == "list_sports":
        return f'Listed sports matching "{a.get("query") or "all"}": {r.get("total", 0)}.', None
    if n == "search_venues":
        k = r.get("counts", {})
        fac = ", ".join(FACILITY_LABEL.get(f, f) for f in a.get("facilities") or []) or "no facility filter"
        return (
            f"Searched {a.get('sport')} venues within 10 km of {r.get('place')}, facility band {r.get('distance_limit_m')} m, {fac}: "
            f"{k.get('total_for_sport')} found, {k.get('matched')} matched, {k.get('undocumented')} with no published information, {k.get('not_available')} recording none."
        ), _search_href("search_venues", a)
    if n == "get_venue":
        return (
            f"Read the record of {r.get('name')}: four facilities, access chain, {r.get('upcoming_events', {}).get('count', 0)} upcoming event(s).",
            r.get("href"),
        )
    if n == "search_events":
        w = r.get("window", {})
        filt = ", ".join(f"{k} {v}" for k, v in a.items() if v and k != "date_from" and k != "date_to") or "no filter"
        return (
            f"Searched events {w.get('from')} to {w.get('to')}, {filt}: {r.get('total')} found, {r.get('unmatched_venue')} at venues not in our list.",
            _search_href("search_events", a),
        )
    if n == "get_event":
        return f"Read the event {r.get('title')}.", r.get("href")
    if n == "search_program_descriptions":
        if not r.get("available", True):
            return "Program descriptions were not searched (retrieval not configured).", None
        ps = r.get("passages", [])
        return (
            f"Read {len(ps)} passage(s) from AAA Play program descriptions."
            if ps
            else "Searched the AAA Play program descriptions: nothing relevant enough."
        ), None
    return f"Called {n}.", None


def build_trace(calls: list[dict]) -> list[dict]:
    """The "what I checked" panel, one entry per tool call, written by the backend."""
    out = []
    for i, c in enumerate(calls, 1):
        summary, href = _summary(c)
        entry: dict[str, Any] = {"step": i, "tool": c["name"], "summary": summary}
        if href:
            entry["href"] = href
        if c["name"] == "search_program_descriptions":
            entry["passages"] = [
                {
                    "program_id": p["program_id"],
                    "title": p.get("title"),
                    "quote": p["text"][:240],
                    "href": p["href"],
                    "source": "AAA Play activity finder",
                }
                for p in c["result"].get("passages", [])
            ]
        out.append(entry)
    return out


# ----------------------------------------------------------------- sources
def build_sources(calls: list[dict]) -> list[dict]:
    """Every dataset a fact in this turn came from, with the publisher's date, de-duplicated."""
    seen: dict[str, dict] = {}
    for c in calls:
        for d in _walk(c["result"]):
            s = d.get("source")
            if isinstance(s, dict) and s.get("name"):
                seen.setdefault(
                    s["name"],
                    {"name": s["name"], "publisher_last_updated": s.get("publisher_last_updated")},
                )
        if c["name"] == "search_program_descriptions" and c["result"].get("passages"):
            seen.setdefault(
                "AAA Play activity finder",
                {"name": "AAA Play activity finder", "publisher_last_updated": None},
            )
        for line in c["result"].get("attribution", []) if isinstance(c["result"], dict) else []:
            seen.setdefault(
                "AAA Play activity finder",
                {"name": "AAA Play activity finder", "publisher_last_updated": None},
            )["attribution"] = line
    return list(seen.values())


# ---------------------------------------------------------------- response
def build_response(final: dict, tool_calls: list[str], payloads: list[str], model_called: bool = True) -> dict:
    """The contract response (section A shape) from the model's final_answer and the tool results."""
    calls = _calls(tool_calls, payloads)
    venues, events = seen_venues(calls), seen_events(calls)
    answer, removed = scrub(final.get("answer", ""), seen_links(calls))
    links, dropped = build_links(final.get("actions") or [], calls, venues, events)
    result_events = [events[i] for i in final.get("event_ids", []) if i in events]
    seen_hrefs = {link["href"] for link in links}
    links += [link for link in event_links(result_events) if link["href"] not in seen_hrefs]
    return {
        "kind": final.get("kind", "answer"),
        "answer": answer,
        "results": {
            "venues": [venues[i] for i in final.get("venue_ids", []) if i in venues],
            "events": result_events,
        },
        "links": links,
        "sources": build_sources(calls),
        "trace": build_trace(calls),
        "suggested_questions": (final.get("suggested_questions") or [])[:3],
        "notice": NOTICE,
        "model_called": model_called,
        "builder": {
            "urls_removed_from_answer": removed,
            "actions_dropped": dropped,
            "ids_not_seen": [
                i
                for i in final.get("venue_ids", []) + final.get("event_ids", [])
                if i not in venues and i not in events
            ],
        },
    }

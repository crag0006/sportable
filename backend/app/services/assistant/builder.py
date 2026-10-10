"""Turn the model's ``final_answer`` plus the tool results into the response (section 8.3).

The model names ids and intents. Every link, every source chip and the whole
"what I checked" trace are produced here from the tool payloads, so nothing
the model wrote can become a link, a source or a step. Any URL left in the
answer text that no tool returned is removed. Measured on 10 Oct: across 62
answers from two models, zero links came from the model.
"""

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from app.schemas.assistant import (
    AssistantResponse,
    CalendarItemOut,
    CalendarProposalOut,
    LinkOut,
    NotExportableOut,
    PassageOut,
    ResultsOut,
    SourceChipOut,
    TraceStepOut,
)

URL_IN_TEXT = re.compile(r"(?:https?://[^\s)\]>\"']+|/(?:venues|events|api)[A-Za-z0-9:_/?=&%.-]*)")
FACILITY_LABEL = {
    "accessible_toilet": "accessible toilet",
    "accessible_parking": "accessible parking",
    "accessible_transport_stop": "step-free railway station",
    "accessible_change_facility": "accessible change facility",
}
AAA_PLAY = "AAA Play activity finder"


@dataclass(frozen=True)
class Call:
    """One tool call the loop made, with its arguments and result."""

    name: str
    args: dict[str, Any]
    result: dict[str, Any]


@dataclass
class Seen:
    """Everything the tool results of one turn exposed: the whitelist for links and cards."""

    venues: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    links: set[str] = field(default_factory=set)


def _walk(node: Any) -> Any:
    """Every dict inside a JSON value, depth first."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


LINK_KEYS = ("href", "external", "publisher_page", "registration", "share_url", "ics_url")


def _note(seen: Seen, d: dict[str, Any]) -> None:
    """Record what one dict of a tool result exposes: links, a venue card, an event card."""
    for key in LINK_KEYS:
        if isinstance(d.get(key), str) and d[key]:
            seen.links.add(d[key])
    for url in d.get("google_template_urls") or []:
        if isinstance(url, str):
            seen.links.add(url)
    href = d.get("href")
    if isinstance(href, str) and href.startswith("/venues/") and "id" in d and "name" in d:
        seen.venues.setdefault(d["id"], d)
    elif d.get("matched") is True and d.get("id") and d.get("name") and "href" not in d:
        card = {"id": d["id"], "name": d["name"], "suburb": d.get("suburb")}
        seen.venues.setdefault(d["id"], {**card, "href": f"/venues/{d['id']}"})
    if isinstance(href, str) and href.startswith("/events/") and "id" in d and "title" in d:
        seen.events.setdefault(d["id"], d)
    elif isinstance(href, str) and href.startswith("/events/") and "program_id" in d:
        title = d.get("title") or d["program_id"]
        seen.events.setdefault(
            d["program_id"], {"id": d["program_id"], "title": title, "href": href}
        )


def seen_in(calls: list[Call]) -> Seen:
    """Collect the venues, events and links the tool results carried."""
    seen = Seen()
    for c in calls:
        for d in _walk(c.result):
            _note(seen, d)
    return seen


def scrub(answer: str, allowed: set[str]) -> tuple[str, list[str]]:
    """Remove every URL or path in the text that no tool returned; report what was removed."""
    removed: list[str] = []

    def keep_or_drop(m: re.Match[str]) -> str:
        """Keep a link the tools returned, drop any other."""
        link = m.group(0).rstrip(".,;:)")
        if link in allowed:
            return m.group(0)
        removed.append(link)
        return m.group(0)[len(link) :]  # keep the sentence's own punctuation

    text = URL_IN_TEXT.sub(keep_or_drop, answer)
    text = re.sub(
        r"[ \t]*(?:Page|Pages|Full list|Links?|Venue page|Details)\s*:\s*(?=\n|$)", "", text
    )
    return re.sub(r"[ \t]+\n", "\n", text).strip(), removed


# ------------------------------------------------------------------ actions
def _search_href(kind: str, a: dict[str, Any]) -> str:
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


def _ran_search(calls: list[Call], kind: str, a: dict[str, Any]) -> Call | None:
    """The tool call this search action repeats, or None when no such search was run."""
    tool = "search_venues" if kind == "search_venues" else "search_events"
    for c in calls:
        if c.name == tool and "error" not in c.result:
            same_sport = (c.args.get("sport") or "").lower() == (a.get("sport") or "").lower()
            same_place = (c.args.get("location") or "").lower() == (a.get("location") or "").lower()
            if same_sport and same_place:
                return c
    return None


def _link_for(a: dict[str, Any], calls: list[Call], seen: Seen) -> LinkOut | None:
    """One action as a link, or None when nothing in this turn backs it."""
    kind = a.get("kind")
    if kind == "venue" and a.get("venue_id") in seen.venues:
        v = seen.venues[a["venue_id"]]
        return LinkOut(kind="venue", label=f"Open {v['name']}", href=v["href"])
    if kind == "event" and a.get("event_id") in seen.events:
        e = seen.events[a["event_id"]]
        return LinkOut(kind="event", label=f"Open {e['title']}", href=e["href"])
    if kind in ("search_venues", "search_events"):
        c = _ran_search(calls, kind, a)
        if c is None:
            return None
        total = c.result.get("counts", {}).get("total_for_sport") or c.result.get("total")
        what = f"{a.get('sport') or 'all'} {'venues' if kind == 'search_venues' else 'events'}"
        where = f" near {a.get('location')}" if a.get("location") else ""
        label = f"See all {total} {what}{where}" if total else f"See {what}{where}"
        return LinkOut(kind="search", label=label, href=_search_href(kind, a))
    if kind == "directions" and a.get("venue_id") in seen.venues and a.get("from"):
        v = seen.venues[a["venue_id"]]
        return LinkOut(
            kind="directions",
            label=f"Directions to {v['name']}",
            href=f"/venues/{a['venue_id']}/directions?" + urlencode({"from": a["from"]}),
        )
    return None


def build_links(actions: list[dict[str, Any]], calls: list[Call], seen: Seen) -> list[LinkOut]:
    """Validated actions as links, de-duplicated by href; calendar_add is handled separately."""
    links: list[LinkOut] = []
    hrefs: set[str] = set()
    for a in actions:
        if a.get("kind") == "calendar_add":
            continue
        link = _link_for(a, calls, seen)
        if link is not None and link.href not in hrefs:
            links.append(link)
            hrefs.add(link.href)
    return links


def event_links(events: list[dict[str, Any]]) -> list[LinkOut]:
    """Registration and publisher-page buttons for the event cards in the answer."""
    out: list[LinkOut] = []
    for e in events:
        if e.get("registration"):
            out.append(
                LinkOut(
                    kind="registration", label=f"Register for {e['title']}", href=e["registration"]
                )
            )
        if e.get("external"):
            out.append(
                LinkOut(
                    kind="publisher", label=f"View {e['title']} on AAA Play", href=e["external"]
                )
            )
    return out


# ------------------------------------------------------------------- trace
def _lookup_summary(n: str, a: dict[str, Any], r: dict[str, Any]) -> tuple[str, str | None] | None:
    """The sentence for the lookup tools (location, venue name, sports, one venue, one event)."""
    if n == "resolve_location":
        if r.get("outcome") == "resolved":
            return f'Resolved "{a.get("query")}" to {r.get("label")}.', None
        sugg = ", ".join(r.get("suggestions") or []) or "none"
        return (
            f'Could not resolve "{a.get("query")}" ({r.get("outcome")}); suggestions: {sugg}.',
            None,
        )
    if n == "find_venue":
        found = len(r.get("candidates", []))
        return f'Looked up venues named "{a.get("name")}": {found} candidate(s).', None
    if n == "list_sports":
        return f'Listed sports matching "{a.get("query") or "all"}": {r.get("total", 0)}.', None
    if n == "get_venue":
        count = r.get("upcoming_events", {}).get("count", 0)
        text = (
            f"Read the record of {r.get('name')}: four facilities, access chain, "
            f"{count} upcoming event(s)."
        )
        return text, r.get("href")
    if n == "get_event":
        return f"Read the event {r.get('title')}.", r.get("href")
    return None


def _summary(c: Call) -> tuple[str, str | None]:
    """One sentence per tool call, written from the call and its result, plus an optional href."""
    n, a, r = c.name, c.args, c.result
    if "error" in r:
        return f"{n} returned {r['error']}: {r.get('message') or ''}".strip(), None
    lookup = _lookup_summary(n, a, r)
    if lookup is not None:
        return lookup
    if n == "search_venues":
        ran = {**a, "distance_m": r.get("distance_limit_m")}  # the band actually used
        return _search_venues_summary(a, r), _search_href("search_venues", ran)
    if n == "search_events":
        w = r.get("window", {})
        filt = ", ".join(
            f"{k} {v}" for k, v in a.items() if v and k not in ("date_from", "date_to")
        )
        text = (
            f"Searched events {w.get('from')} to {w.get('to')}, {filt or 'no filter'}: "
            f"{r.get('total')} found, {r.get('unmatched_venue')} at venues not in our list."
        )
        return text, _search_href("search_events", a)
    if n == "search_program_descriptions":
        if not r.get("available", True):
            return "Program descriptions were not searched (retrieval not configured).", None
        ps = r.get("passages", [])
        if ps:
            return f"Read {len(ps)} passage(s) from AAA Play program descriptions.", None
        return "Searched the AAA Play program descriptions: nothing relevant enough.", None
    return f"Called {n}.", None


def _search_venues_summary(a: dict[str, Any], r: dict[str, Any]) -> str:
    """The sentence for a venue search, with the group counts."""
    k = r.get("counts", {})
    fac = (
        ", ".join(FACILITY_LABEL.get(f, f) for f in a.get("facilities") or [])
        or "no facility filter"
    )
    return (
        f"Searched {a.get('sport')} venues within 10 km of {r.get('place')}, facility band "
        f"{r.get('distance_limit_m')} m, {fac}: {k.get('total_for_sport')} found, "
        f"{k.get('matched')} matched, {k.get('undocumented')} with no published information, "
        f"{k.get('not_available')} recording none."
    )


def build_trace(calls: list[Call]) -> list[TraceStepOut]:
    """The "what I checked" panel, one entry per tool call, written by the server."""
    out: list[TraceStepOut] = []
    for i, c in enumerate(calls, 1):
        summary, href = _summary(c)
        passages = (
            [
                PassageOut(
                    program_id=p["program_id"],
                    title=p.get("title"),
                    quote=p["text"][:240],
                    href=p["href"],
                    source=AAA_PLAY,
                )
                for p in c.result.get("passages", [])
            ]
            if c.name == "search_program_descriptions"
            else []
        )
        out.append(TraceStepOut(step=i, tool=c.name, summary=summary, href=href, passages=passages))
    return out


def build_sources(calls: list[Call]) -> list[SourceChipOut]:
    """Every dataset a fact in this turn came from, with the publisher's date, de-duplicated."""
    seen: dict[str, SourceChipOut] = {}
    for c in calls:
        for d in _walk(c.result):
            s = d.get("source")
            if isinstance(s, dict) and s.get("name"):
                seen.setdefault(
                    s["name"],
                    SourceChipOut(
                        name=s["name"], publisher_last_updated=s.get("publisher_last_updated")
                    ),
                )
        if c.name == "search_program_descriptions" and c.result.get("passages"):
            seen.setdefault(AAA_PLAY, SourceChipOut(name=AAA_PLAY))
        for line in c.result.get("attribution", []) or []:
            seen[AAA_PLAY] = SourceChipOut(name=AAA_PLAY, attribution=line)
    return list(seen.values())


# ---------------------------------------------------------------- calendar
def _calendar_item(e: dict[str, Any]) -> CalendarItemOut | NotExportableOut:
    """One chosen event as a proposal item, or the sentence saying why it cannot be exported.

    The block is the event's ``calendar`` object (contract section 7.7), passed
    through as the tool returned it.
    """
    cal = e.get("calendar") if isinstance(e.get("calendar"), dict) else None
    if not cal or not cal.get("exportable"):
        message = (cal or {}).get("message") or "This event cannot be added to a calendar."
        return NotExportableOut(event_id=e["id"], title=e["title"], message=message)
    urls: list[str] = cal.get("google_template_urls") or []
    slots = [h.get("slot") for h in cal.get("time_hints") or []]
    links = [
        LinkOut(
            kind="google_template",
            label="Add to Google Calendar"
            + (f" ({slots[i]})" if len(urls) > 1 and i < len(slots) else ""),
            href=url,
        )
        for i, url in enumerate(urls)
    ]
    if cal.get("ics_url"):
        links.append(LinkOut(kind="ics", label="Download .ics", href=cal["ics_url"]))
    lines = cal.get("description_lines") or []
    when = lines[0] if lines else e.get("when", "")
    title = cal.get("title") or e["title"]
    return CalendarItemOut(event_id=e["id"], title=title, when=when, calendar=cal, links=links)


def build_calendar_proposal(
    actions: list[dict[str, Any]], seen: Seen
) -> CalendarProposalOut | None:
    """The proposal for the events the user picked, from ``calendar_add`` actions (section 8.10)."""
    ids: list[str] = []
    for a in actions:
        if a.get("kind") == "calendar_add":
            ids.extend(i for i in (a.get("event_ids") or []) if i in seen.events and i not in ids)
    if not ids:
        return None
    proposal = CalendarProposalOut()
    for i in ids:
        item = _calendar_item(seen.events[i])
        if isinstance(item, CalendarItemOut):
            proposal.items.append(item)
        else:
            proposal.not_exportable.append(item)
    exportable = [it.event_id for it in proposal.items]
    if exportable:
        label = "Download as one file" if len(exportable) > 1 else "Download .ics"
        proposal.download_all = LinkOut(
            kind="ics", label=label, href="/api/v1/events/calendar.ics?ids=" + ",".join(exportable)
        )
    return proposal


# ---------------------------------------------------------------- response
def build_response(
    final: dict[str, Any], calls: list[Call], *, model_called: bool, partial: bool
) -> AssistantResponse:
    """The contract response from the model's final_answer and the tool results."""
    seen = seen_in(calls)
    answer, _removed = scrub(str(final.get("answer", "")), seen.links)
    actions = [a for a in (final.get("actions") or []) if isinstance(a, dict)]
    links = build_links(actions, calls, seen)
    event_cards = [seen.events[i] for i in final.get("event_ids", []) if i in seen.events]
    hrefs = {link.href for link in links}
    links += [link for link in event_links(event_cards) if link.href not in hrefs]
    kind = (
        final.get("kind")
        if final.get("kind") in ("answer", "results", "clarify", "no_information", "capability")
        else "answer"
    )
    return AssistantResponse(
        kind=kind,
        answer=answer,
        results=ResultsOut(
            venues=[seen.venues[i] for i in final.get("venue_ids", []) if i in seen.venues],
            events=event_cards,
        ),
        links=links,
        sources=build_sources(calls),
        trace=build_trace(calls),
        suggested_questions=[str(q) for q in (final.get("suggested_questions") or [])][:3],
        calendar_proposal=build_calendar_proposal(actions, seen),
        model_called=model_called,
        partial=partial,
    )

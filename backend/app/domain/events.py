"""Events: build the response objects of contract v0.2 section 7 from event rows.

The one rule that matters: the four tiles beside an event are the venue's
own tiles, read from the same rows as the venue page (AC4.2.2 / AC5.2.1).
An unmatched venue gets four "no published information" tiles and a
sentence saying why (AC4.2.3 / AC5.2.2). Nothing here infers access from a
title, a description or a publisher's tag.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.facilities import KINDS, present, presentations_for, verdict
from app.domain.ics import build_ics
from app.domain.presenters import _iso, facility_out, reference_out
from app.domain.provenance import source_ref
from app.repositories.protocols import EventRow, ReferencePoint
from app.schemas.common import FacilityOut, ReferencePointOut
from app.schemas.events import (
    EventAccessOut,
    EventLinksOut,
    EventOut,
    EventSourceOut,
    EventVenueOut,
    RecurrenceOut,
    WindowOut,
)

STATUS_LABELS: dict[str, str] = {
    "UPCOMING": "Scheduled",
    "PENDING": "Scheduled",
    "FINAL": "Finished",
    "CANCELLED": "Cancelled",
    "ABANDONED": "Abandoned",
    "ACTIVE": "Runs weekly",
}
WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
TIME_LABELS: dict[str, str] = {
    "morning": "mornings",
    "afternoon": "afternoons",
    "evening": "evenings",
    "after_school": "after school",
    "all_day": "all day",
    "school_holiday_program": "school holidays",
}
UNMATCHED_MESSAGE = (
    "This venue is not in our venue list, so we have no published access information for it."
)
WINDOW_RULE = (
    "Fixtures are listed when their start time falls inside the window. "
    "Programs are listed when one of their weekdays falls inside the window, "
    "or when the publisher stated no weekday."
)


def _label_days(days: Sequence[str]) -> str:
    """``Mondays, Wednesdays and Fridays`` in weekday order."""
    names = [d.capitalize() + "s" for d in WEEKDAYS if d in days]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def recurrence_out(row: EventRow) -> RecurrenceOut | None:
    """The weekly pattern of a program; None for a fixture."""
    if row.kind != "program":
        return None
    days = [d for d in WEEKDAYS if d in row.weekdays]
    times = [TIME_LABELS.get(t, t.replace("_", " ")) for t in row.time_of_day]
    if days:
        summary = _label_days(days)
        if times:
            summary += ", " + " and ".join(times)
    else:
        summary = "Days not stated by the publisher"
        if times:
            summary += " (" + " and ".join(times) + ")"
    return RecurrenceOut(
        weekdays=days,
        time_of_day=list(row.time_of_day),
        days_stated=bool(days),
        summary=summary,
    )


def local_time(row: EventRow) -> datetime | None:
    """A fixture's start in the event's timezone; None for a program."""
    if row.starts_at is None:
        return None
    return row.starts_at.astimezone(ZoneInfo(row.timezone))


def tiles_for(row: EventRow, limit_m: int, stale_default: int) -> list[FacilityOut]:
    """The venue's own four tiles, or four unknowns when the venue is unmatched."""
    if row.venue is not None:
        return [facility_out(p, stale_default) for p in presentations_for(row.venue, limit_m)]
    return [facility_out(present(None, kind, limit_m), stale_default) for kind in KINDS]


def access_summary(tiles: list[FacilityOut]) -> str:
    """One sentence per state, for the list row and the calendar file."""
    parts: list[str] = []
    unknown: list[str] = []
    for tile in tiles:
        label = tile.label
        if tile.display == "at_venue":
            parts.append(f"{label} at the venue.")
        elif tile.display == "nearby":
            parts.append(f"{label} {tile.distance_m} m away.")
        elif tile.display == "beyond_limit":
            parts.append(
                f"Nearest {label.lower()} {tile.distance_m} m away, beyond the "
                f"{tile.distance_limit_m} m limit."
            )
        elif tile.display == "not_available_alternative" and tile.alternative is not None:
            parts.append(
                f"No {label.lower()} at the venue; nearest public one "
                f"{tile.alternative.distance_m} m away."
            )
        elif tile.display == "not_available":
            parts.append(f"No {label.lower()} at the venue.")
        else:
            unknown.append(label.lower())
    if unknown:
        joined = unknown[0] if len(unknown) == 1 else ", ".join(unknown[:-1]) + " or " + unknown[-1]
        parts.append(f"No published information for {joined}.")
    return " ".join(parts)


def group_of(tiles: list[FacilityOut], kinds: Sequence[str]) -> str | None:
    """matched / undocumented / not_available for the requested kinds; None without a filter."""
    if not kinds:
        return None
    by_kind: dict[str, FacilityOut] = {t.type: t for t in tiles}
    verdicts = set()
    for kind in kinds:
        tile = by_kind.get(kind)
        if tile is None:
            continue
        p = present(None, kind, tile.distance_limit_m)
        # verdict() reads status only; rebuild a minimal presentation from the tile.
        p = p.__class__(**{**p.__dict__, "status": tile.status})
        verdicts.add(verdict(p))
    if "fail" in verdicts:
        return "not_available"
    if "open" in verdicts:
        return "undocumented"
    return "matched"


@dataclass(frozen=True)
class Built:
    out: EventOut
    group: str | None


def _event_venue_out(row: EventRow) -> EventVenueOut:
    """The matched DS-01 venue, or the publisher's own place with the reason."""
    matched = row.venue is not None
    v = row.venue
    return EventVenueOut(
        matched=matched,
        match_basis=row.venue_match_basis,
        venue_id=row.venue_id if matched else None,
        name=v.name if v is not None else row.venue_name,
        address=v.address if v is not None else row.venue_address,
        suburb=v.suburb if v is not None else row.venue_suburb,
        postcode=v.postcode if v is not None else row.venue_postcode,
        latitude=v.latitude if v is not None else row.venue_lat,
        longitude=v.longitude if v is not None else row.venue_lon,
        href=f"/venues/{row.venue_id}" if matched else None,
        message=None if matched else UNMATCHED_MESSAGE,
    )


def _event_source_out(row: EventRow, stale_default: int) -> EventSourceOut:
    """Provenance of the event: the publisher's date, our retrieval, staleness."""
    ref = source_ref(
        row.source_name,
        source_id=row.source_id,
        publisher_last_updated=row.publisher_updated_at or row.source_publisher_last_updated,
        retrieved_at=row.retrieved_at,
        stale_after_days=row.source_stale_after_days,
        default_stale_after_days=stale_default,
    )
    assert ref is not None
    return EventSourceOut(
        id=ref.id,
        name=ref.name,
        publisher_last_updated=_iso(ref.publisher_last_updated),
        retrieved_at=_iso(ref.retrieved_at),
        possibly_out_of_date=ref.possibly_out_of_date,
        stale_after_days=ref.stale_after_days,
        attribution=row.source_attribution,
    )


def _event_links_out(row: EventRow, venue: EventVenueOut) -> EventLinksOut:
    """Where to go next: detail, venue, directions, calendar file, publisher."""
    matched = row.venue is not None
    return EventLinksOut(
        detail=f"/events/{row.event_id}",
        venue=venue.href,
        directions=f"/venues/{row.venue_id}/directions" if matched else None,
        ics=f"/api/v1/events/{row.event_id}.ics",
        external=row.external_url,
        registration=row.registration_url,
    )


def _timing(row: EventRow) -> dict[str, Any]:
    """Fixture instants in local time; all None for a program (R1)."""
    local = local_time(row)
    tz = ZoneInfo(row.timezone)
    return {
        "starts_at": local.isoformat() if local else None,
        "ends_at": row.ends_at.astimezone(tz).isoformat() if row.ends_at else None,
        "date_local": local.date().isoformat() if local else None,
        "time_local": local.strftime("%H:%M") if local else None,
    }


def _requested_met(tiles: list[FacilityOut], kinds: Sequence[str]) -> bool | None:
    """Whether every requested kind is confirmed at the band; None without a filter."""
    if not kinds:
        return None
    by_kind = {t.type: t for t in tiles}
    return all(by_kind[k].status == "confirmed" for k in kinds if k in by_kind)


def _identity(row: EventRow) -> dict[str, Any]:
    """What the event is: names, competition, status, price, audience."""
    return {
        "id": row.event_id,
        "kind": row.kind,
        "title": row.title,
        "sport": row.sport,
        "sport_raw": row.sport_raw,
        "competition": row.competition,
        "season": row.season,
        "grade": row.grade,
        "round": row.round,
        "home_team": row.home_team,
        "away_team": row.away_team,
        "organisation": row.organisation,
        "description": row.description,
        "status": row.status,
        "status_label": STATUS_LABELS.get(row.status, row.status.title()),
        "timezone": row.timezone,
        "recurrence": recurrence_out(row),
        "price": row.price,
        "age_ranges": list(row.age_ranges),
        "access_needs": list(row.access_needs),
    }


def event_out(
    row: EventRow,
    *,
    limit_m: int,
    stale_default: int,
    kinds: Sequence[str],
) -> Built:
    """One event as the contract's event object, with its venue's four tiles."""
    tiles = tiles_for(row, limit_m, stale_default)
    grp = group_of(tiles, kinds)
    venue = _event_venue_out(row)
    out = EventOut(
        **_identity(row),
        **_timing(row),
        venue=venue,
        distance_m=round(row.distance_m) if row.distance_m is not None else None,
        access=EventAccessOut(
            facilities=tiles,
            requested_met=_requested_met(tiles, kinds),
            group=grp,
            summary=access_summary(tiles),
        ),
        links=_event_links_out(row, venue),
        source=_event_source_out(row, stale_default),
    )
    return Built(out, grp)


def weekdays_in_window(date_from: date, date_to: date) -> tuple[str, ...] | None:
    """The weekday names a window contains, or None when it holds a whole week.

    One rule for ``/events`` and ``/events/sports``: the list applies it in
    Python, the sports count applies it in SQL, both from this function.
    """
    span = (date_to - date_from).days
    if span >= 6:
        return None
    return tuple(WEEKDAYS[(date_from + timedelta(days=i)).weekday()] for i in range(span + 1))


def in_window(row: EventRow, date_from: date, date_to: date) -> bool:
    """The window rule for programs; fixtures were selected in SQL."""
    if row.kind != "program":
        return True
    if not row.weekdays:
        return True
    days = weekdays_in_window(date_from, date_to)
    if days is None:
        return True
    return bool(set(days) & set(row.weekdays))


def counts_by_date(rows: Sequence[EventRow], date_from: date, date_to: date) -> dict[str, int]:
    """Events per local date, for the calendar grid (AC5.1.2)."""
    out: dict[str, int] = {}
    span = (date_to - date_from).days
    dates = [date_from + timedelta(days=i) for i in range(span + 1)]
    for row in rows:
        if row.kind == "fixture":
            local = local_time(row)
            if local is not None:
                key = local.date().isoformat()
                out[key] = out.get(key, 0) + 1
        elif row.weekdays:
            for d in dates:
                if WEEKDAYS[d.weekday()] in row.weekdays:
                    key = d.isoformat()
                    out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def empty_message(sports: Sequence[str], date_from: date, date_to: date, place: str | None) -> str:
    """The sentence for an empty list, naming the three remedies."""
    what = ", ".join(sports) + " events" if sports else "events"
    where = f" near {place}" if place else ""
    return (
        f"No {what} found{where} between {date_from.isoformat()} and {date_to.isoformat()}. "
        "Try a wider date range, remove a filter, or try a nearby suburb."
    )


def window_out(date_from: date, date_to: date, timezone: str) -> WindowOut:
    """The applied window with the rule that selected programs for it."""
    return WindowOut(
        **{"from": date_from.isoformat()},
        to=date_to.isoformat(),
        timezone=timezone,
        rule=WINDOW_RULE,
    )


def reference_for(reference: ReferencePoint | None) -> ReferencePointOut | None:
    """The reference point as the contract shows it, or None."""
    return reference_out(reference) if reference is not None else None


def event_ics(row: EventRow, out: EventOut, share_url: str, now: datetime | None = None) -> str:
    """The iCalendar file for one event: summary, timing, venue, access summary, links."""
    venue_line = ", ".join(p for p in (out.venue.name, out.venue.address) if p)
    description_parts = [
        " · ".join(p for p in (out.sport or out.sport_raw, out.grade, out.round) if p),
        out.recurrence.summary if out.recurrence else None,
        out.access.summary,
        f"Venue page: {share_url.rsplit('/events/', 1)[0]}{out.links.venue}"
        if out.links.venue
        else None,
        f"Publisher page: {out.links.external}",
        out.source.attribution,
        "End time is estimated." if row.kind == "fixture" and row.ends_at is None else None,
        "Times for weekly programs are as published by the provider."
        if row.kind == "program"
        else None,
    ]
    status = "CANCELLED" if row.status in ("CANCELLED", "ABANDONED") else "CONFIRMED"
    summary = (
        f"{out.sport or out.sport_raw}: {out.title}" if (out.sport or out.sport_raw) else out.title
    )
    return build_ics(
        uid=f"{row.event_id}@sportablemelbourne.me",
        summary=summary,
        description="\n".join(p for p in description_parts if p),
        location=venue_line or None,
        url=share_url,
        status=status,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        weekdays=row.weekdays,
        timezone=row.timezone,
        latitude=out.venue.latitude,
        longitude=out.venue.longitude,
        now=now,
    )

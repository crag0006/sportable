"""Events over the DS-09 program tables (data/sql/009).

One "event" in the API is one program row: a weekly program today, a dated
fixture when a dated source lands (kind = 'fixture', starts_at set). Nothing
here derives a status: the four tiles come from venue_amenity_status through
program_venue.venue_id, assembled by ``_rows.venues_by_id``.

Listable: every program (they have no status of their own), and a fixture
that has not started yet (AC5.1.3). ``status = all`` lifts the second
condition so a shared link to a past game still resolves.
"""

from datetime import UTC, date, datetime
from typing import Any

from app.core.db import connection
from app.domain.events import weekdays_in_window
from app.domain.matching import match_basis
from app.repositories._rows import SRID, to_date, to_datetime, to_float, venues_by_id
from app.repositories.protocols import EventFilters, EventRow, EventSportRow, UpcomingRow, VenueRow

EVENT_LISTABLE = """
    (p.kind = 'program' OR %(include_past)s OR p.starts_at > %(now)s)
"""

# The publisher's sport labels and the vocabulary sports they name, from the
# reviewed crosswalk (data/sql/012). NOT a dict in this file: the mapping is
# data, it is reviewed line by line with a recorded reason, and it is
# many-to-many. "Tennis" names both Tennis (Outdoor) and Tennis (Indoor)
# because the publisher does not say which, and "Bike riding, BMX & cycling"
# names Cycling and BMX; a one-to-one dict here could express neither, and the
# seven entries it did hold covered seven of the twenty-five terms that need
# translating.
#
# Three kinds of row need distinguishing, which is why vocab and labels are
# aggregated separately below:
#   vocab_sport IS NOT NULL   a sport in the venue vocabulary, or one the
#                             crosswalk adds (Boccia, Goalball: real sports
#                             that no DS-01 venue records)
#   relation = 'not_a_sport'  Art, Playground, Special Olympics. Not offered as
#                             a sport; the programme still lists
#   unreviewed                a term the publisher added since the last review.
#                             Shown as published rather than dropped, which is
#                             what the crosswalk's LEFT JOIN is for

EVENT_COLUMNS = """
       p.program_id AS event_id, p.source_id, p.kind::text AS kind, p.name AS title,
       CASE WHEN p.kind = 'program' THEN 'ACTIVE'
            WHEN p.starts_at > %(now)s THEN 'UPCOMING'
            ELSE 'FINAL' END AS status,
       p.source_url AS external_url, p.retrieved_at,
       sp.labels AS sport_labels, sp.vocab AS sport_vocab,
       p.description, o.name AS organisation,
       p.starts_at, p.ends_at,
       p.recurrence_weekdays AS weekdays, p.recurrence_time_of_day AS time_of_day,
       CASE WHEN p.is_free THEN 'free' WHEN p.is_free IS FALSE THEN 'paid' END AS price,
       p.age_ranges, needs.labels AS access_needs,
       p.registration_url,
       pv.program_venue_id AS venue_external_id, pv.name AS venue_name,
       pv.full_address AS venue_address, pv.suburb_name AS venue_suburb,
       pv.postcode AS venue_postcode,
       ST_Y(coalesce(pv.geom, p.geom)) AS venue_lat, ST_X(coalesce(pv.geom, p.geom)) AS venue_lon,
       pv.venue_id, pv.match_distance_m, pv.match_name_similarity,
       p.publisher_last_updated AS publisher_updated_at,
       s.name AS source_name, s.attribution_text AS source_attribution,
       s.publisher_last_updated AS source_publisher_last_updated,
       s.stale_after_days AS source_stale_after_days
"""

EVENT_FROM = """
  FROM program p
  JOIN source s ON s.source_id = p.source_id
  LEFT JOIN program_venue pv ON pv.program_venue_id = p.program_venue_id
  LEFT JOIN program_organisation o ON o.organisation_id = p.organisation_id
  LEFT JOIN LATERAL (
       -- DISTINCT because the crosswalk is many-to-many: "Tennis" is two rows,
       -- so the label would otherwise appear twice. ORDER BY because
       -- sport_raw is labels[0] and an unordered array makes that arbitrary.
       SELECT array_agg(DISTINCT psv.sport_label ORDER BY psv.sport_label)
                FILTER (WHERE psv.relation IS DISTINCT FROM 'not_a_sport')  AS labels,
              array_remove(
                  array_agg(DISTINCT psv.vocab_sport ORDER BY psv.vocab_sport),
                  NULL
              )                                                             AS vocabs,
              -- One name for the card. The filter uses vocabs, all of them.
              min(psv.vocab_sport)                                          AS vocab
         FROM program_sport_vocabulary psv
        WHERE psv.program_id = p.program_id
  ) sp ON true
  LEFT JOIN LATERAL (
       SELECT array_agg(n.access_need_label ORDER BY n.access_need_label) AS labels
         FROM program_access_need n
        WHERE n.program_id = p.program_id
  ) needs ON true
"""

SQL_EVENTS = f"""
WITH ref AS (
    SELECT CASE WHEN %(lat)s::float IS NULL THEN NULL
           ELSE ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), {SRID})::geography END AS g
)
SELECT {EVENT_COLUMNS},
       CASE WHEN ref.g IS NULL THEN NULL
            ELSE ST_Distance(coalesce(pv.geom, p.geom)::geography, ref.g) END AS distance_m
  {EVENT_FROM}
 CROSS JOIN ref
 WHERE (%(status_all)s OR {EVENT_LISTABLE})
   AND (p.kind = 'program'
        OR (p.starts_at AT TIME ZONE 'Australia/Melbourne')::date
           BETWEEN %(date_from)s AND %(date_to)s)
   -- Every vocabulary sport the crosswalk gives this programme, not just the
   -- one on the card: a Tennis programme answers both Tennis (Indoor) and
   -- Tennis (Outdoor). The publisher's own labels still match too, so a filter
   -- built from the events list keeps working for an unreviewed term.
   AND (%(sports)s::text[] IS NULL
        OR EXISTS (SELECT 1 FROM unnest(sp.vocabs) AS v(sport)
                    WHERE lower(v.sport) = ANY(%(sports)s))
        OR EXISTS (SELECT 1 FROM unnest(sp.labels) AS l(label)
                    WHERE lower(l.label) = ANY(%(sports)s)))
   AND (%(venue_id)s::text IS NULL OR pv.venue_id = %(venue_id)s)
   AND (ref.g IS NULL
        OR ST_DWithin(coalesce(pv.geom, p.geom)::geography, ref.g, %(within_m)s))
   AND (%(weekdays)s::text[] IS NULL OR p.recurrence_weekdays && %(weekdays)s)
   AND (%(time_of_day)s::text[] IS NULL
        OR EXISTS (SELECT 1 FROM unnest(p.recurrence_time_of_day) AS t(v)
                    WHERE lower(replace(t.v, ' ', '_')) = ANY(%(time_of_day)s)))
   AND (%(price)s::text IS NULL
        OR (%(price)s = 'free' AND p.is_free) OR (%(price)s = 'paid' AND p.is_free IS FALSE))
 ORDER BY (p.kind = 'fixture') DESC, p.starts_at NULLS LAST, distance_m NULLS LAST, p.name
 LIMIT %(limit)s
"""

SQL_EVENT = f"""
SELECT {EVENT_COLUMNS}, NULL::double precision AS distance_m
  {EVENT_FROM}
 WHERE p.program_id = %(id)s
"""

# One row per sport per programme, not per programme: a programme carrying two
# sports belongs under both, and a term the crosswalk splits belongs under each
# half. Joined straight to the view rather than through EVENT_FROM's aggregate
# for that reason.
#
# A term decided to be not a sport (Art, Playground) yields no name and drops
# out. An unreviewed term keeps its published label, so a taxonomy change
# upstream shows up as a new filter option rather than as events that silently
# cannot be filtered for.
# The same window rule as /events: a program counts when one of its weekdays
# falls inside the window, or when it states no weekday. ``window_days`` is
# NULL for a window of a week or more (every weekday is in it).
SQL_EVENT_SPORTS = f"""
SELECT name, count(DISTINCT program_id) AS event_count
  FROM (
    SELECT p.program_id,
           coalesce(psv.vocab_sport,
                    CASE WHEN psv.unreviewed THEN psv.sport_label END) AS name
      FROM program p
      JOIN program_sport_vocabulary psv ON psv.program_id = p.program_id
     WHERE {EVENT_LISTABLE}
       AND (p.kind = 'program'
            OR (p.starts_at AT TIME ZONE 'Australia/Melbourne')::date
               BETWEEN %(date_from)s AND %(date_to)s)
       AND (p.kind = 'fixture'
            OR %(window_days)s::text[] IS NULL
            OR cardinality(p.recurrence_weekdays) = 0
            OR p.recurrence_weekdays && %(window_days)s::text[])
  ) named
 WHERE name IS NOT NULL
 GROUP BY name
 ORDER BY name
"""

SQL_UPCOMING_AT_VENUE = f"""
SELECT count(*) AS n, min(p.starts_at) FILTER (WHERE p.kind = 'fixture') AS next_starts_at
  FROM program p
  JOIN program_venue pv ON pv.program_venue_id = p.program_venue_id
 WHERE pv.venue_id = %(venue_id)s
   AND {EVENT_LISTABLE}
"""


def _slug(value: str) -> str:
    """``After school`` -> ``after_school``, the API's time-of-day vocabulary."""
    return value.strip().lower().replace(" ", "_")


def _venue_columns(row: dict[str, Any], venue: VenueRow | None) -> dict[str, Any]:
    """The publisher's place, and the DS-01 match when there is one."""
    distance = to_float(row["match_distance_m"])
    similarity = to_float(row["match_name_similarity"])
    matched = venue is not None
    return {
        "venue_external_id": row["venue_external_id"],
        "venue_name": row["venue_name"],
        "venue_address": row["venue_address"],
        "venue_suburb": row["venue_suburb"],
        "venue_postcode": row["venue_postcode"],
        "venue_lat": to_float(row["venue_lat"]),
        "venue_lon": to_float(row["venue_lon"]),
        "venue_id": row["venue_id"] if matched else None,
        "venue_match_basis": match_basis(distance, similarity) if matched else "none",
        "venue_match_distance_m": distance if matched else None,
        "venue": venue,
    }


def _source_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Provenance of the event row: publisher dates and the register entry."""
    return {
        "publisher_updated_at": to_datetime(row["publisher_updated_at"]),
        "source_name": row["source_name"],
        "source_attribution": row["source_attribution"],
        "source_publisher_last_updated": to_date(row["source_publisher_last_updated"]),
        "source_stale_after_days": row["source_stale_after_days"],
    }


def event_row(row: dict[str, Any], venue: VenueRow | None) -> EventRow:
    """One event row as an ``EventRow``. Types only, no rules."""
    labels = tuple(row["sport_labels"] or ())
    return EventRow(
        event_id=row["event_id"],
        source_id=row["source_id"],
        kind=row["kind"],
        title=row["title"],
        status=row["status"],
        external_url=row["external_url"] or "",
        retrieved_at=row["retrieved_at"],
        sport=row["sport_vocab"],
        sport_raw=labels[0] if labels else None,
        description=row["description"],
        organisation=row["organisation"],
        starts_at=to_datetime(row["starts_at"]),
        ends_at=to_datetime(row["ends_at"]),
        timezone="Australia/Melbourne",
        weekdays=tuple(row["weekdays"] or ()),
        # The loader stores the publisher's display labels ("After school");
        # the API vocabulary is the slug ("after_school").
        time_of_day=tuple(_slug(t) for t in (row["time_of_day"] or ())),
        price=row["price"],
        age_ranges=tuple(row["age_ranges"] or ()),
        access_needs=tuple(row["access_needs"] or ()),
        registration_url=row["registration_url"],
        distance_m=to_float(row["distance_m"]),
        **_venue_columns(row, venue),
        **_source_columns(row),
    )


def _filter_params(filters: EventFilters) -> dict[str, Any]:
    """``EventFilters`` as the bind parameters of ``SQL_EVENTS``."""
    reference = filters.reference
    return {
        "lat": reference.latitude if reference else None,
        "lon": reference.longitude if reference else None,
        "within_m": filters.within_m,
        "status_all": filters.status == "all",
        "include_past": filters.include_past,
        "now": filters.now,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
        "sports": [s.lower() for s in filters.sports] or None,
        "venue_id": filters.venue_id,
        "weekdays": list(filters.weekdays) or None,
        "time_of_day": list(filters.time_of_day) or None,
        "price": filters.price,
        "limit": filters.limit,
    }


class PostgresEventRepository:
    """``EventRepository`` over PostGIS."""

    def list_events(self, filters: EventFilters) -> list[EventRow]:
        """Listable events matching the filters, each with its venue's tiles."""
        with connection() as conn:
            rows = conn.execute(SQL_EVENTS, _filter_params(filters)).fetchall()
            venues = venues_by_id(conn, [r["venue_id"] for r in rows if r["venue_id"]])
        return [event_row(r, venues.get(r["venue_id"])) for r in rows]

    def get_event(self, event_id: str) -> EventRow | None:
        """One event by id, whatever its status, or None."""
        params = {"id": event_id, "now": datetime.now(UTC)}
        with connection() as conn:
            row = conn.execute(SQL_EVENT, params).fetchone()
            if row is None:
                return None
            venues = venues_by_id(conn, [row["venue_id"]] if row["venue_id"] else [])
        return event_row(row, venues.get(row["venue_id"]))

    def event_sports(self, date_from: date, date_to: date, now: datetime) -> list[EventSportRow]:
        """Sports with a listable event in the window, through the crosswalk."""
        days = weekdays_in_window(date_from, date_to)
        params = {
            "date_from": date_from,
            "date_to": date_to,
            "now": now,
            "include_past": False,
            "window_days": list(days) if days is not None else None,
        }
        with connection() as conn:
            rows = conn.execute(SQL_EVENT_SPORTS, params).fetchall()
        return [EventSportRow(name=r["name"], event_count=int(r["event_count"])) for r in rows]

    def upcoming_events(self, venue_id: str, now: datetime) -> UpcomingRow:
        """Listable event count at a venue and the next fixture start, if any."""
        params = {"venue_id": venue_id, "now": now, "include_past": False}
        with connection() as conn:
            row = conn.execute(SQL_UPCOMING_AT_VENUE, params).fetchone()
        if row is None:
            return UpcomingRow(0, None)
        return UpcomingRow(int(row["n"]), to_datetime(row["next_starts_at"]))

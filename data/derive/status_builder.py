"""
Build accessibility status for each venue from the loaded
venues and amenities.

Writes:
    venue_amenity_status
    venue_access_chain

Then refreshes the materialized views used by the API.

The access chain has six links:
    arrive_parking
    arrive_transport
    toilet
    change
    enter
    play

The venue's own published accessibility information takes priority over
nearby public facilities. Nearby facilities are still stored so the API
can show them separately.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

LOG = logging.getLogger("sportable.status_builder")

SRID = 7844

BANDS_M = (250, 500, 1000)

# Status is confirmed using the largest distance band.
# The API applies the actual distance limit using the within_* fields.
CONFIRM_WITHIN_M = max(BANDS_M)

SEARCH_RADIUS_M = 5000
CANDIDATE_RADIUS_DEG = 0.08

CONFIRMED = "confirmed"
NOT_AVAILABLE = "not_available"
NO_INFO = "no_published_information"

# If a venue has already confirmed an on-site facility, a nearby DS-02
# record can provide extra details such as opening hours.
DETAIL_ATTACH_M = 50

VENUE_SOURCE_ID = "DS-01"

# Venue attributes that directly publish information about these facilities.
# Change facilities and transport stops only come from nearby amenities.
KINDS = {
    "accessible_toilet": "onsite_accessible_toilet",
    "accessible_parking": "onsite_accessible_parking",
    "accessible_change_facility": None,
    "accessible_transport_stop": None,
}

# Each access chain link maps to one facility kind.
LINK_KIND = {
    "arrive_parking": "accessible_parking",
    "arrive_transport": "accessible_transport_stop",
    "toilet": "accessible_toilet",
    "change": "accessible_change_facility",
    "enter": None,
    "play": None,
}

UNPUBLISHED_DETAIL = {
    "enter": (
        "No Australian open dataset publishes step-free entry at venue level. "
        "Recorded as unpublished rather than estimated."
    ),
    "play": (
        "No Australian open dataset publishes access to the playing surface at "
        "venue level. Recorded as unpublished rather than estimated."
    ),
}

READ_MODEL_VIEWS = ("venue_card", "sport_vocabulary", "search_location")


@dataclass
class StatusOutcome:
    load_run_id: int
    venues: int
    status_rows: int
    chain_rows: int
    by_kind: dict[str, dict[str, int]]
    attachments: dict[str, dict[str, int]] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "Status builder",
            f"  venues                 {self.venues:,}",
            f"  status rows written    {self.status_rows:,}",
            f"  chain rows written     {self.chain_rows:,}",
        ]

        for kind, counts in self.by_kind.items():
            total = sum(counts.values()) or 1
            confirmed = counts.get(CONFIRMED, 0)

            lines.append(f"  {kind}")

            for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
                lines.append(f"    {status:<26} {n:,}")

            lines.append(f"    {'confirmed share':<26} {round(100 * confirmed / total, 1)}%")

            extra = self.attachments.get(kind, {})

            if extra.get("details"):
                lines.append(f"    {'detail attached':<26} {extra['details']:,}")

            if extra.get("alternatives"):
                lines.append(f"    {'nearby alternative shown':<26} {extra['alternatives']:,}")

        return "\n".join(lines)


def _nearest_sql(kind: str) -> str:
    """Find the nearest amenity of a particular kind for each venue."""

    return f"""
        SELECT v.venue_id,
               n.amenity_id,
               n.source_id,
               n.distance_m
          FROM venue v
          LEFT JOIN LATERAL (
               SELECT a.amenity_id,
                      a.source_id,
                      ST_Distance(
                          a.geom::geography,
                          v.geom::geography
                      ) AS distance_m
                 FROM amenity a
                WHERE a.kind = %(kind)s
                  AND ST_DWithin(a.geom, v.geom, {CANDIDATE_RADIUS_DEG})
                ORDER BY a.geom <-> v.geom
                LIMIT 20
          ) n ON true
    """


def build(conn, load_run_id: int) -> StatusOutcome:
    """Build the venue accessibility statuses and access chain."""

    venues = conn.execute("SELECT count(*) AS n FROM venue").fetchone()["n"]

    if venues == 0:
        raise RuntimeError("No venues loaded. Run the DS-01 load before the status builder.")

    # Check which amenity kinds are currently available.
    present = {
        r["kind"]
        for r in conn.execute("SELECT DISTINCT kind::text AS kind FROM amenity").fetchall()
    }

    for kind in KINDS:
        if kind not in present:
            LOG.warning(
                "%s has no loaded amenities. Every venue will report no "
                "published information for it.",
                kind,
            )

    venue_attributes = {
        r["venue_id"]: r
        for r in conn.execute(
            """
            SELECT venue_id,
                   onsite_accessible_toilet::text AS accessible_toilet,
                   onsite_accessible_parking::text AS accessible_parking
              FROM venue
            """
        ).fetchall()
    }

    status_rows: list[tuple] = []
    by_kind: dict[str, dict[str, int]] = {}
    attachments: dict[str, dict[str, int]] = {}

    for kind, venue_column in KINDS.items():
        nearest: dict[str, tuple[str | None, str | None, float | None]] = {}

        if kind in present:
            for row in conn.execute(_nearest_sql(kind), {"kind": kind}).fetchall():
                vid = row["venue_id"]
                aid = row["amenity_id"]
                dist = row["distance_m"]

                if aid is None or dist is None or dist > SEARCH_RADIUS_M:
                    nearest.setdefault(vid, (None, None, None))
                    continue

                current = nearest.get(vid)

                if current is None or current[2] is None or dist < current[2]:
                    nearest[vid] = (aid, row["source_id"], float(dist))

        counts: dict[str, int] = {}
        attached = {"alternatives": 0, "details": 0}

        for venue_id, attributes in venue_attributes.items():
            amenity_id, amenity_source, distance = nearest.get(
                venue_id,
                (None, None, None),
            )

            published = None

            if venue_column:
                published = attributes[venue_column.replace("onsite_", "")]

            near_enough = distance is not None and distance <= CONFIRM_WITHIN_M

            # The venue's own published value always takes priority.
            # Nearby facilities are only used when the venue has not
            # published a yes/no value.
            source_id: str | None = None
            if published == CONFIRMED:
                status = CONFIRMED
                basis = "publisher_attribute"
                source_id = VENUE_SOURCE_ID

            elif published == NOT_AVAILABLE:
                status = NOT_AVAILABLE
                basis = "publisher_attribute"
                source_id = VENUE_SOURCE_ID

            elif near_enough:
                status = CONFIRMED
                basis = "spatial_proximity"
                source_id = amenity_source

            elif kind not in present:
                status = NO_INFO
                basis = "not_published"
                source_id = None

            else:
                status = NO_INFO
                basis = "spatial_proximity"
                source_id = None

            keep_amenity = amenity_id if distance is not None else None

            keep_distance = round(distance, 1) if distance is not None else None

            # Keep a nearby public facility as an alternative when the
            # venue itself says that it does not have the facility.
            alternative_amenity = None
            alternative_distance = None

            if status == NOT_AVAILABLE and amenity_id is not None and keep_distance is not None:
                alternative_amenity = amenity_id
                alternative_distance = keep_distance

            # Attach extra details from a nearby record when the venue
            # already confirmed that the facility exists.
            detail_amenity = None
            detail_source = None
            detail_distance = None

            if (
                status == CONFIRMED
                and basis == "publisher_attribute"
                and amenity_id is not None
                and keep_distance is not None
                and keep_distance <= DETAIL_ATTACH_M
            ):
                detail_amenity = amenity_id
                detail_source = amenity_source
                detail_distance = keep_distance

            status_rows.append(
                (
                    venue_id,
                    kind,
                    load_run_id,
                    status,
                    basis,
                    source_id,
                    keep_amenity,
                    keep_distance,
                    keep_distance is not None and keep_distance <= 250,
                    keep_distance is not None and keep_distance <= 500,
                    keep_distance is not None and keep_distance <= 1000,
                    alternative_amenity,
                    alternative_distance,
                    detail_amenity,
                    detail_source,
                    detail_distance,
                )
            )

            if alternative_amenity is not None:
                attached["alternatives"] += 1

            if detail_amenity is not None:
                attached["details"] += 1

            counts[status] = counts.get(status, 0) + 1

        by_kind[kind] = counts
        attachments[kind] = attached

    with conn.cursor() as cur:
        cur.execute("DELETE FROM venue_amenity_status")

        cur.executemany(
            """
            INSERT INTO venue_amenity_status
                (venue_id, kind, load_run_id, status, basis, source_id,
                 nearest_amenity_id, distance_m,
                 within_250m, within_500m, within_1000m,
                 alternative_amenity_id, alternative_distance_m,
                 detail_amenity_id, detail_source_id, detail_distance_m)
            VALUES (
                %s, %s::amenity_kind, %s,
                %s::publication_status, %s::status_basis, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            status_rows,
        )

    chain_rows = _build_chain(conn)

    refresh_read_model(conn)

    return StatusOutcome(
        load_run_id=load_run_id,
        venues=venues,
        status_rows=len(status_rows),
        chain_rows=chain_rows,
        by_kind=by_kind,
        attachments=attachments,
    )


def _build_chain(conn) -> int:
    """Build the six access chain rows for each venue."""

    rows: list[tuple] = []

    statuses: dict[str, dict[str, Any]] = {}

    for r in conn.execute(
        """
        SELECT venue_id,
               kind::text AS kind,
               status::text AS status,
               basis::text AS basis,
               distance_m
          FROM venue_amenity_status
        """
    ).fetchall():
        statuses.setdefault(r["venue_id"], {})[r["kind"]] = r

    for venue_id in statuses:
        for link, kind in LINK_KIND.items():
            if kind is None:
                rows.append(
                    (
                        venue_id,
                        link,
                        None,
                        NO_INFO,
                        "not_published",
                        UNPUBLISHED_DETAIL[link],
                    )
                )
                continue

            record = statuses[venue_id].get(kind)

            if record is None:
                rows.append(
                    (
                        venue_id,
                        link,
                        kind,
                        NO_INFO,
                        "not_published",
                        "No source in the register answers this for this venue.",
                    )
                )
                continue

            rows.append(
                (
                    venue_id,
                    link,
                    kind,
                    record["status"],
                    record["basis"],
                    _detail_for(record),
                )
            )

    with conn.cursor() as cur:
        cur.execute("DELETE FROM venue_access_chain")

        cur.executemany(
            """
            INSERT INTO venue_access_chain
                (venue_id, link, kind, status, basis, detail)
            VALUES (
                %s,
                %s::access_link,
                %s::amenity_kind,
                %s::publication_status,
                %s::status_basis,
                %s
            )
            """,
            rows,
        )

    return len(rows)


def _detail_for(record: dict[str, Any]) -> str:
    """Create a short description of where the status came from."""

    facility = record["kind"].replace("accessible_", "").replace("_", " ")

    if record["basis"] == "publisher_attribute":
        if record["status"] == CONFIRMED:
            return f"The venue's own record publishes {facility} on site."

        if record["status"] == NOT_AVAILABLE:
            return f"The venue's own record states there is no {facility} on site."

    if record["status"] == CONFIRMED and record["distance_m"] is not None:
        return (
            f"Nearest published {facility} is "
            f"{int(record['distance_m'])} m away. It is a separate public "
            "facility, not the venue's own."
        )

    if record["distance_m"] is not None:
        return (
            f"Nearest published {facility} is "
            f"{int(record['distance_m'])} m away, beyond the "
            f"{CONFIRM_WITHIN_M} m limit."
        )

    return "No source in the register answers this for this venue."


def refresh_read_model(conn) -> None:
    """Refresh the materialized views used by the API."""

    for view in READ_MODEL_VIEWS:
        try:
            with conn.cursor() as cur:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")

        except Exception as error:
            LOG.warning(
                "Concurrent refresh of %s failed (%s). Falling back to a "
                "blocking refresh, which is expected on the first run after "
                "the read model is created.",
                view,
                error,
            )
            conn.rollback()

            with conn.cursor() as cur:
                cur.execute(f"REFRESH MATERIALIZED VIEW {view}")

        LOG.info("refreshed %s", view)

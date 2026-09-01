"""
Builds the accessibility status for each venue based on the loaded
venues and amenities.

Writes:
    venue_amenity_status
    venue_access_chain
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

LOG = logging.getLogger("sportable.status_builder")

SRID = 7844

BANDS_M = (250, 500, 1000)
CONFIRM_WITHIN_M = max(BANDS_M)

SEARCH_RADIUS_M = 5000
CANDIDATE_RADIUS_DEG = 0.08

CONFIRMED = "confirmed"
NOT_AVAILABLE = "not_available"
NO_INFO = "no_published_information"

KINDS = {
    "accessible_toilet": "onsite_accessible_toilet",
    "accessible_parking": "onsite_accessible_parking",
    "accessible_change_facility": None,
    "accessible_transport_stop": None,
}

LINK_SOURCES = {
    "arrive": ("accessible_transport_stop", "accessible_parking"),
    "enter": (),
    "toilet": ("accessible_toilet",),
    "change": ("accessible_change_facility",),
    "play": (),
}


@dataclass
class StatusOutcome:
    load_run_id: int
    venues: int
    status_rows: int
    chain_rows: int
    by_kind: dict[str, dict[str, int]]

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

        return "\n".join(lines)


def _nearest_sql(kind: str) -> str:
    """Find the nearest amenity for each venue."""

    return f"""
        SELECT v.venue_id,
               n.amenity_id,
               n.distance_m
          FROM venue v
          LEFT JOIN LATERAL (
               SELECT a.amenity_id,
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

    # Get the amenity types currently loaded.
    present = {
        r["kind"]
        for r in conn.execute("SELECT DISTINCT kind::text AS kind FROM amenity").fetchall()
    }

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

    for kind, venue_column in KINDS.items():
        nearest: dict[str, tuple[str | None, float | None]] = {}

        if kind in present:
            for row in conn.execute(_nearest_sql(kind), {"kind": kind}).fetchall():
                vid = row["venue_id"]
                aid = row["amenity_id"]
                dist = row["distance_m"]

                if aid is None or dist is None or dist > SEARCH_RADIUS_M:
                    nearest.setdefault(vid, (None, None))
                    continue

                current = nearest.get(vid)

                if current is None or current[1] is None or dist < current[1]:
                    nearest[vid] = (aid, float(dist))

        counts: dict[str, int] = {}

        for venue_id, attributes in venue_attributes.items():
            amenity_id, distance = nearest.get(venue_id, (None, None))

            published = None

            if venue_column:
                published = attributes[venue_column.replace("onsite_", "")]

            near_enough = distance is not None and distance <= CONFIRM_WITHIN_M

            # Venue-level information takes priority over nearby amenities.
            if published == CONFIRMED:
                status = CONFIRMED
                basis = "publisher_attribute"

            elif near_enough:
                status = CONFIRMED
                basis = "spatial_proximity"

            elif kind not in present:
                status = NO_INFO
                basis = "not_published"

            elif published == NOT_AVAILABLE:
                status = NOT_AVAILABLE
                basis = "publisher_attribute"

            else:
                status = NO_INFO
                basis = "spatial_proximity"

            keep_amenity = amenity_id if distance is not None else None

            keep_distance = round(distance, 1) if distance is not None else None

            status_rows.append(
                (
                    venue_id,
                    kind,
                    load_run_id,
                    status,
                    basis,
                    keep_amenity,
                    keep_distance,
                    keep_distance is not None and keep_distance <= 250,
                    keep_distance is not None and keep_distance <= 500,
                    keep_distance is not None and keep_distance <= 1000,
                )
            )

            counts[status] = counts.get(status, 0) + 1

        by_kind[kind] = counts

    with conn.cursor() as cur:
        cur.execute("DELETE FROM venue_amenity_status")

        cur.executemany(
            """
            INSERT INTO venue_amenity_status
                (venue_id, kind, load_run_id, status, basis,
                 nearest_amenity_id, distance_m,
                 within_250m, within_500m, within_1000m)
            VALUES (
                %s, %s::amenity_kind, %s,
                %s::publication_status, %s::status_basis,
                %s, %s, %s, %s, %s
            )
            """,
            status_rows,
        )

    chain_rows = _build_chain(conn, venues)

    return StatusOutcome(
        load_run_id=load_run_id,
        venues=venues,
        status_rows=len(status_rows),
        chain_rows=chain_rows,
        by_kind=by_kind,
    )


def _build_chain(conn, venues: int) -> int:
    """Build the five access chain rows for each venue."""

    rows: list[tuple] = []

    statuses: dict[Any, dict[str, Any]] = {}

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
        for link, kinds in LINK_SOURCES.items():
            if not kinds:
                rows.append(
                    (
                        venue_id,
                        link,
                        NO_INFO,
                        "not_published",
                        "No Australian open dataset publishes this at "
                        "venue level. Recorded as unpublished rather than "
                        "estimated.",
                    )
                )
                continue

            candidates = [statuses[venue_id][k] for k in kinds if k in statuses[venue_id]]

            confirmed = [c for c in candidates if c["status"] == CONFIRMED]

            if confirmed:
                best = min(
                    confirmed,
                    key=lambda c: (
                        c["basis"] != "publisher_attribute",
                        c["distance_m"] or 0,
                    ),
                )

                if best["basis"] == "publisher_attribute":
                    detail = f"published at the venue ({best['kind'].replace('_', ' ')})"
                else:
                    detail = (
                        f"nearest {best['kind'].replace('_', ' ')} {int(best['distance_m'])} m away"
                    )

                rows.append(
                    (
                        venue_id,
                        link,
                        CONFIRMED,
                        best["basis"],
                        detail,
                    )
                )

            elif any(c["status"] == NOT_AVAILABLE for c in candidates):
                rows.append(
                    (
                        venue_id,
                        link,
                        NOT_AVAILABLE,
                        "publisher_attribute",
                        "the venue's own record states this is not available",
                    )
                )

            else:
                rows.append(
                    (
                        venue_id,
                        link,
                        NO_INFO,
                        "spatial_proximity",
                        "no source in the register answers this for this venue",
                    )
                )

    with conn.cursor() as cur:
        cur.execute("DELETE FROM venue_access_chain")

        cur.executemany(
            """
            INSERT INTO venue_access_chain
                (venue_id, link, status, basis, detail)
            VALUES (
                %s,
                %s::access_link,
                %s::publication_status,
                %s::status_basis,
                %s
            )
            """,
            rows,
        )

    return len(rows)

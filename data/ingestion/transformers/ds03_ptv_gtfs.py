"""
ingestion/transformers/ds03_ptv_gtfs.py

Transform DS-03 GTFS stops into accessible transport stop amenities.

The caller handles unpacking the GTFS archive and combining the different
mode feeds. This file only works with the stops DataFrame it receives.

Main rules:
- Use (mode_id, stop_id) as the natural key.
- Represent one arrival place as one amenity.
- Child stops inherit wheelchair_boarding from their parent when needed.
- Only wheelchair_boarding = 1 is loaded as an accessible stop.
- Invalid coordinates are quarantined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SOURCE_ID = "DS-03"
KIND_STOP = "accessible_transport_stop"

# GTFS location_type values.
LOCATION_STOP_OR_PLATFORM = 0
LOCATION_STATION = 1

# GTFS wheelchair_boarding values.
WB_INHERIT_OR_UNKNOWN = 0
WB_ACCESSIBLE = 1
WB_NOT_ACCESSIBLE = 2

REQUIRED_COLUMNS = (
    "stop_id",
    "stop_name",
    "stop_lat",
    "stop_lon",
    "mode_id",
    "mode",
)


@dataclass
class TransformResult:
    amenities: pd.DataFrame
    quarantine: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats

        lines = [
            "DS-03 transform",
            f"  stop rows read           {s.get('rows_read', 0):,}",
            f"  distinct (mode, stop)    {s.get('distinct_keys', 0):,}",
            f"  inherited from parent    {s.get('inherited', 0):,}",
            f"  arrival places           {s.get('arrival_places', 0):,}",
            "",
            "  wheelchair_boarding at arrival-place grain",
            f"    1 confirmed            {s.get('wb_confirmed', 0):,}",
            f"    2 published absence    {s.get('wb_not_accessible', 0):,}",
            f"    0 or empty unknown     {s.get('wb_unknown', 0):,}",
            f"    unknown share          {s.get('wb_unknown_pct', 0)}%",
            "",
            f"  amenities loaded         {len(self.amenities):,}",
            f"  quarantined              {len(self.quarantine):,}",
        ]

        by_mode = s.get("emitted_by_mode") or {}

        if by_mode:
            lines.append("")
            lines.append("  emitted by mode")

            for mode, n in sorted(by_mode.items(), key=lambda kv: -kv[1]):
                lines.append(f"    {mode:<22} {n:,}")

        return "\n".join(lines)


def _clean(value: Any) -> str | None:
    """Clean a value and return None when it is empty."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    s = str(value).strip()

    if not s or s.lower() in {"nan", "none", "null"}:
        return None

    return s


def _wheelchair_value(value: Any) -> int:
    """Convert wheelchair_boarding to an integer value."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return WB_INHERIT_OR_UNKNOWN

    text = str(value).strip()

    if not text or text.lower() in {"nan", "none", "null"}:
        return WB_INHERIT_OR_UNKNOWN

    try:
        return int(float(text))
    except (TypeError, ValueError):
        return WB_INHERIT_OR_UNKNOWN


def _reason_for_coordinates(lat: Any, lon: Any) -> str | None:
    """Return the quarantine reason for invalid coordinates."""
    lat_n = pd.to_numeric(lat, errors="coerce")
    lon_n = pd.to_numeric(lon, errors="coerce")

    if pd.isna(lat_n) or pd.isna(lon_n):
        return "COORD_MISSING"

    if -90 <= lat_n <= 90 and -180 <= lon_n <= 180:
        return None

    if -90 <= lon_n <= 90 and -180 <= lat_n <= 180:
        return "COORD_TRANSPOSED"

    return "COORD_INVALID"


def apply_parent_inheritance(
    stops: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Fill missing child wheelchair_boarding from the parent station."""
    df = stops.copy()

    if "wheelchair_boarding" in df.columns:
        df["wheelchair_boarding_raw"] = df["wheelchair_boarding"].map(_wheelchair_value)
    else:
        df["wheelchair_boarding_raw"] = WB_INHERIT_OR_UNKNOWN

    if "parent_station" in df.columns:
        parent_column = df["parent_station"].map(_clean)
    else:
        parent_column = pd.Series(
            [None] * len(df),
            index=df.index,
        )

    df["parent_key"] = parent_column

    parents = {
        (row["mode_id"], row["stop_id"]): row["wheelchair_boarding_raw"] for _, row in df.iterrows()
    }

    effective = []
    inherited = 0

    for _, row in df.iterrows():
        own = row["wheelchair_boarding_raw"]
        parent = row["parent_key"]

        if own != WB_INHERIT_OR_UNKNOWN or parent is None:
            effective.append(own)
            continue

        from_parent = parents.get((row["mode_id"], parent))

        if from_parent is not None and from_parent != WB_INHERIT_OR_UNKNOWN:
            effective.append(from_parent)
            inherited += 1
        else:
            effective.append(own)

    df["wheelchair_boarding_effective"] = effective

    return df, inherited


def select_arrival_places(stops: pd.DataFrame) -> pd.DataFrame:
    """Keep one row for each place where a person actually arrives."""
    if "location_type" in stops.columns:
        location_type = stops["location_type"].map(_wheelchair_value)
    else:
        location_type = pd.Series(
            [LOCATION_STOP_OR_PLATFORM] * len(stops),
            index=stops.index,
        )

    is_station = location_type == LOCATION_STATION
    has_no_parent = stops["parent_key"].isna()

    return stops[is_station | has_no_parent].copy()


def transform(
    stops: pd.DataFrame,
    load_run_id: int | None = None,
    retrieved_at: Any = None,
) -> TransformResult:
    """Transform DS-03 GTFS stops into amenities and quarantine rows."""

    stats: dict[str, Any] = {"rows_read": len(stops)}

    missing = [c for c in REQUIRED_COLUMNS if c not in stops.columns]

    if missing:
        raise ValueError(f"DS-03 stops frame is missing required columns: {missing}")

    df = stops.copy()

    df["stop_id"] = df["stop_id"].map(lambda v: _clean(v) or "")
    df["mode_id"] = df["mode_id"].map(lambda v: _clean(v) or "")

    # The natural key is (mode_id, stop_id).
    # Duplicate stop_id values across modes are allowed.
    key = df["mode_id"] + ":" + df["stop_id"]
    duplicated = int(key.duplicated().sum())

    if duplicated:
        raise ValueError(
            f"DS-03 has {duplicated} duplicate (mode_id, stop_id) pairs. "
            "The natural key contract is broken and the load must not proceed."
        )

    stats["distinct_keys"] = int(key.nunique())

    df, inherited = apply_parent_inheritance(df)
    stats["inherited"] = inherited

    places = select_arrival_places(df)
    stats["arrival_places"] = len(places)

    counts = places["wheelchair_boarding_effective"].value_counts().to_dict()

    confirmed_n = int(counts.get(WB_ACCESSIBLE, 0))
    absent_n = int(counts.get(WB_NOT_ACCESSIBLE, 0))
    unknown_n = len(places) - confirmed_n - absent_n

    stats["wb_confirmed"] = confirmed_n
    stats["wb_not_accessible"] = absent_n
    stats["wb_unknown"] = unknown_n
    stats["wb_unknown_pct"] = round(
        100 * unknown_n / (len(places) or 1),
        1,
    )

    amenity_rows: list[dict] = []
    quarantine_rows: list[dict] = []
    by_mode: dict[str, int] = {}

    for _, row in places.iterrows():
        mode_id = row["mode_id"]
        stop_id = row["stop_id"]
        natural_key = f"{mode_id}:{stop_id}"

        # Only published accessible stops are loaded.
        if row["wheelchair_boarding_effective"] != WB_ACCESSIBLE:
            continue

        lat, lon = row.get("stop_lat"), row.get("stop_lon")
        reason = _reason_for_coordinates(lat, lon)

        if reason is not None:
            quarantine_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "natural_key": natural_key,
                    "reason": reason,
                    "detail": f"stop_lat={lat!r} stop_lon={lon!r}",
                    "payload": {
                        "mode_id": mode_id,
                        "stop_id": stop_id,
                        "stop_name": _clean(row.get("stop_name")),
                        "mode": _clean(row.get("mode")),
                    },
                }
            )
            continue

        mode = _clean(row.get("mode"))

        amenity_rows.append(
            {
                "amenity_id": f"{SOURCE_ID}:{natural_key}",
                "source_id": SOURCE_ID,
                "load_run_id": load_run_id,
                "kind": KIND_STOP,
                "name": _clean(row.get("stop_name")),
                "address": None,
                "latitude": float(pd.to_numeric(lat)),
                "longitude": float(pd.to_numeric(lon)),
                "opening_hours": None,
                "key_required": None,
                "mlak_24h": None,
                "payment_required": None,
                "access_note": None,
                "facility_note": None,
                "ambulant": None,
                "left_hand_transfer": None,
                "right_hand_transfer": None,
                "accessible_parking_on_site": None,
                "changing_places": None,
                "byo_sling": None,
                "has_shower": None,
                "is_inside_venue": False,
                "key_is_derived": False,
                "transport_mode": mode,
                "wheelchair_boarding": WB_ACCESSIBLE,
                "stop_code": _clean(row.get("stop_code")),
                "retrieved_at": retrieved_at,
            }
        )

        if mode:
            by_mode[mode] = by_mode.get(mode, 0) + 1

    amenities = pd.DataFrame(amenity_rows)
    quarantine = pd.DataFrame(quarantine_rows)

    stats["emitted_by_mode"] = by_mode
    stats["quarantine_rate_pct"] = round(
        100 * len(quarantine) / (confirmed_n or 1),
        2,
    )

    if len(amenities):
        duplicate_ids = int(amenities["amenity_id"].duplicated().sum())

        if duplicate_ids:
            raise ValueError(
                f"DS-03 produced {duplicate_ids} duplicate amenity_id values. "
                "The derived key is not unique and the load must not proceed."
            )

    return TransformResult(
        amenities=amenities,
        quarantine=quarantine,
        stats=stats,
    )

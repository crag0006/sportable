"""
ingestion/transformers/ds04_accessible_parking.py

Transforms the raw DS-04 KML data into accessible parking amenity rows.

DS-04 provides accessible parking bays for the central city. The input is
already a GeoDataFrame, so this function only handles the transformation and
does not do any file, database or network work.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SOURCE_ID = "DS-04"
KIND_PARKING = "accessible_parking"

# Column used by the publisher to identify the type of parking.
USAGE_COLUMN = "___UsageType"

# Known values for accessible parking.
ACCESSIBLE_USAGE_VALUES = {
    "disable parking",
    "disabled parking",
    "accessible parking",
}

# Used when creating the ID because the source does not provide one.
KEY_PRECISION = 7

# Maximum difference allowed between the KML geometry and the coordinate
# attributes in the source.
COORD_AGREEMENT_TOLERANCE_DEG = 0.000005


@dataclass
class TransformResult:
    amenities: pd.DataFrame
    quarantine: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats

        lines = [
            "DS-04 transform",
            f"  features read            {s.get('features_read', 0):,}",
            f"  accessible bays          {s.get('accessible_bays', 0):,}",
            f"  other categories skipped {s.get('other_categories_skipped', 0):,}",
            f"  amenities loaded         {len(self.amenities):,}",
            f"  quarantined              {len(self.quarantine):,}"
            f"  ({s.get('quarantine_rate_pct', 0)}% of features read)",
        ]

        if s.get("usage_vocabulary"):
            lines.append("  usage vocabulary")

            for value, n in s["usage_vocabulary"].items():
                lines.append(f"    {value!r:<28} {n:,}")

        if len(self.quarantine):
            lines.append("  quarantine by reason")

            for reason, n in self.quarantine["reason"].value_counts().items():
                lines.append(f"    {reason:<24} {n:,}")

        if s.get("distinct_street_segments") is not None:
            lines.append(f"  distinct street segments {s['distinct_street_segments']:,}")

        return "\n".join(lines)


# Helpers


def _clean(value: Any) -> str | None:
    """Clean a text value and return None when it is empty."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    s = str(value).replace("\ufeff", "")
    s = re.sub(r"\s+", " ", s).strip()

    return s or None


def derived_key(latitude: float, longitude: float, name: str | None) -> str:
    """Create a repeatable ID using the coordinates and street description."""
    parts = (
        f"{round(latitude, KEY_PRECISION)}",
        f"{round(longitude, KEY_PRECISION)}",
        _clean(name) or "",
    )

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    return digest[:16]


def _coordinates(
    row: pd.Series,
    geometry: Any,
) -> tuple[float | None, float | None, str | None]:
    """Get coordinates from the geometry and check them against the source."""
    if geometry is None or getattr(geometry, "is_empty", True):
        return None, None, "COORD_MISSING"

    try:
        lat_geom, lon_geom = float(geometry.y), float(geometry.x)
    except Exception:
        return None, None, "COORD_INVALID"

    if not (-90 <= lat_geom <= 90 and -180 <= lon_geom <= 180):
        if -90 <= lon_geom <= 90 and -180 <= lat_geom <= 180:
            return None, None, "COORD_TRANSPOSED"

        return None, None, "COORD_INVALID"

    # Check the coordinates stored in the attributes against the geometry.
    lat_attr = pd.to_numeric(row.get("Latitude"), errors="coerce")
    lon_attr = pd.to_numeric(row.get("Longitude"), errors="coerce")

    if pd.notna(lat_attr) and pd.notna(lon_attr):
        drift = max(
            abs(lat_attr - lat_geom),
            abs(lon_attr - lon_geom),
        )

        if drift > COORD_AGREEMENT_TOLERANCE_DEG:
            return None, None, "SCHEMA_VIOLATION"

    return lat_geom, lon_geom, None


# Transform


def transform(
    raw,
    load_run_id: int | None = None,
    retrieved_at: Any = None,
) -> TransformResult:
    """Convert the DS-04 KML data into amenity and quarantine rows."""

    stats: dict[str, Any] = {"features_read": len(raw)}

    if "geometry" not in raw.columns:
        raise ValueError("DS-04 payload has no geometry column")

    df = raw.copy()

    if USAGE_COLUMN in df.columns:
        vocabulary = df[USAGE_COLUMN].fillna("(null)").astype(str).value_counts()

        stats["usage_vocabulary"] = vocabulary.to_dict()

        usage_normalised = df[USAGE_COLUMN].astype(str).str.strip().str.lower()

        is_accessible = usage_normalised.isin(ACCESSIBLE_USAGE_VALUES)

        unrecognised = sorted(set(usage_normalised[~is_accessible]))

        if unrecognised:
            stats["unrecognised_usage_values"] = unrecognised

    else:
        stats["usage_vocabulary"] = {}
        is_accessible = pd.Series(True, index=df.index)
        stats["usage_column_absent"] = True

    stats["accessible_bays"] = int(is_accessible.sum())
    stats["other_categories_skipped"] = int((~is_accessible).sum())

    df = df[is_accessible]

    name_column = "Name" if "Name" in df.columns else None

    amenity_rows: list[dict] = []
    quarantine_rows: list[dict] = []

    for _, row in df.iterrows():
        geometry = row.get("geometry")
        name = _clean(row.get(name_column)) if name_column else None

        latitude, longitude, reason = _coordinates(
            row,
            geometry,
        )

        if reason is not None:
            quarantine_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "natural_key": None,
                    "reason": reason,
                    "detail": (
                        "the geometry and the published Latitude/Longitude attributes disagree"
                        if reason == "SCHEMA_VIOLATION"
                        else f"geometry={geometry!r}"
                    ),
                    "payload": {
                        "name": name,
                        "usage_type": _clean(row.get(USAGE_COLUMN)),
                        "published_latitude": _clean(row.get("Latitude")),
                        "published_longitude": _clean(row.get("Longitude")),
                    },
                }
            )
            continue

        # _coordinates returns a reason whenever it could not produce a usable
        # pair, so both are real floats past the guard above. Stated explicitly
        # because mypy cannot narrow them through `reason`.
        assert latitude is not None and longitude is not None

        amenity_rows.append(
            {
                "amenity_id": f"{SOURCE_ID}:{derived_key(latitude, longitude, name)}",
                "source_id": SOURCE_ID,
                "load_run_id": load_run_id,
                "kind": KIND_PARKING,
                "name": name,
                "address": name,
                "latitude": latitude,
                "longitude": longitude,
                "usage_type_published": _clean(row.get(USAGE_COLUMN)),
                "is_inside_venue": False,
                "key_is_derived": True,
                "key_required": None,
                "mlak_24h": None,
                "payment_required": None,
                "opening_hours": None,
                "access_note": None,
                "facility_note": None,
                "retrieved_at": retrieved_at,
            }
        )

    amenities = pd.DataFrame(amenity_rows)
    quarantine = pd.DataFrame(quarantine_rows)

    read = stats["features_read"] or 1

    stats["quarantine_rate_pct"] = round(
        100 * len(quarantine) / read,
        2,
    )

    stats["distinct_street_segments"] = int(amenities["name"].nunique()) if len(amenities) else 0

    if len(amenities):
        collisions = int(amenities["amenity_id"].duplicated().sum())

        if collisions:
            raise ValueError(
                f"DS-04 produced {collisions} colliding derived keys. "
                f"Features share the same rounded coordinates and street description. "
                "Resolve before loading."
            )

    return TransformResult(
        amenities=amenities,
        quarantine=quarantine,
        stats=stats,
    )

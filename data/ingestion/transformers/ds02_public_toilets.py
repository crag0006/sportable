"""
ingestion/transformers/ds02_public_toilets.py

Transforms the raw DS-02 public toilet data into amenity rows.

DS-02 is used for two parts of the access chain:
- accessible toilets
- accessible change facilities

The transformer only handles the dataframe transformation. Database loading,
file handling and network requests are done elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SOURCE_ID = "DS-02"

# DS-02 contains data for different states. We only need Victoria here.
STATE = "VIC"

KIND_TOILET = "accessible_toilet"
KIND_CHANGE = "accessible_change_facility"

# Columns needed for the basic transformation.
REQUIRED_COLUMNS = [
    "FacilityID",
    "State",
    "Latitude",
    "Longitude",
    "Accessible",
]


@dataclass
class TransformResult:
    amenities: pd.DataFrame
    quarantine: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats
        lines = [
            "DS-02 transform",
            f"  rows read                {s.get('rows_read', 0):,}",
            f"  Victorian rows           {s.get('rows_in_state', 0):,}",
            f"  accessible toilets       {s.get('toilets_emitted', 0):,}",
            f"  change facilities        {s.get('change_emitted', 0):,}",
            f"    of which Changing Places {s.get('changing_places', 0):,}",
            f"  amenities loaded         {len(self.amenities):,}",
            f"  quarantined              {len(self.quarantine):,}"
            f"  ({s.get('quarantine_rate_pct', 0)}% of Victorian rows)",
        ]

        if len(self.quarantine):
            lines.append("  quarantine by reason")
            for reason, n in self.quarantine["reason"].value_counts().items():
                lines.append(f"    {reason:<24} {n:,}")

        conditions = s.get("conditions", {})

        if conditions:
            lines.append("  conditions on accessible toilets")
            for label, n in conditions.items():
                lines.append(f"    {label:<24} {n:,}")

        return "\n".join(lines)


# Helpers


def _clean(value: Any) -> str | None:
    """Clean a value and return None when it is empty."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    s = re.sub(r"\s+", " ", str(value)).strip()
    return s or None


def _flag(value: Any) -> bool | None:
    """Convert the different boolean values in the source to True/False."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    if isinstance(value, bool):
        return value

    s = str(value).strip().lower()

    if s in {"true", "t", "yes", "y", "1"}:
        return True

    if s in {"false", "f", "no", "n", "0"}:
        return False

    return None


def _reason_for_coordinates(lat: Any, lon: Any) -> str | None:
    """Check the coordinates and return a quarantine reason if needed."""
    lat_n = pd.to_numeric(lat, errors="coerce")
    lon_n = pd.to_numeric(lon, errors="coerce")

    if pd.isna(lat_n) or pd.isna(lon_n):
        return "COORD_MISSING"

    if -90 <= lat_n <= 90 and -180 <= lon_n <= 180:
        return None

    if -90 <= lon_n <= 90 and -180 <= lat_n <= 180:
        return "COORD_TRANSPOSED"

    return "COORD_INVALID"


def _address(row: pd.Series) -> str | None:
    """Build the address using the fields provided by the source."""
    parts = [
        _clean(row.get("Address1")),
        _clean(row.get("Town")),
        _clean(row.get("State")),
    ]

    return ", ".join(p for p in parts if p) or None


def _notes(*values: Any) -> str | None:
    """Combine the available note fields into one string."""
    seen: list[str] = []

    for v in values:
        cleaned = _clean(v)

        if cleaned and cleaned not in seen:
            seen.append(cleaned)

    return " ".join(seen) or None


# Transform


def transform(
    raw: pd.DataFrame,
    load_run_id: int | None = None,
    retrieved_at: Any = None,
) -> TransformResult:
    """Convert DS-02 into amenity and quarantine rows."""

    stats: dict[str, Any] = {"rows_read": len(raw)}

    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]

    if missing:
        raise ValueError(f"DS-02 export is missing required columns: {missing}")

    # Keep Victorian records only.
    df = raw[raw["State"].astype(str).str.strip().str.upper() == STATE].copy()
    stats["rows_in_state"] = len(df)

    # FacilityID should be unique in the source.
    duplicated = int(df["FacilityID"].duplicated().sum())

    if duplicated:
        raise ValueError(
            f"DS-02 FacilityID is not unique within {STATE}: {duplicated} duplicates. "
            "The natural key contract is broken and the load must not proceed."
        )

    amenity_rows: list[dict] = []
    quarantine_rows: list[dict] = []

    toilets = 0
    changes = 0
    changing_places = 0

    conditions = {
        "key required": 0,
        "MLAK 24 hour": 0,
        "payment required": 0,
        "opening hours stated": 0,
    }

    for _, row in df.iterrows():
        facility_id = _clean(row.get("FacilityID"))
        lat, lon = row.get("Latitude"), row.get("Longitude")

        accessible = _flag(row.get("Accessible"))
        changing = _flag(row.get("ChangingPlaces"))
        adult_change = _flag(row.get("AdultChange"))

        has_change = bool(changing) or bool(adult_change)

        # No amenity to add for this row.
        if not accessible and not has_change:
            continue

        reason = _reason_for_coordinates(lat, lon)

        if reason is not None:
            quarantine_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "natural_key": facility_id,
                    "reason": reason,
                    "detail": f"latitude={lat!r} longitude={lon!r}",
                    "payload": {
                        "facility_id": facility_id,
                        "name": _clean(row.get("Name")),
                        "town": _clean(row.get("Town")),
                        "accessible": accessible,
                        "has_change_facility": has_change,
                    },
                }
            )
            continue

        base = {
            "source_id": SOURCE_ID,
            "load_run_id": load_run_id,
            "name": _clean(row.get("Name")),
            "address": _address(row),
            "latitude": float(pd.to_numeric(lat)),
            "longitude": float(pd.to_numeric(lon)),
            "opening_hours": _notes(
                row.get("OpeningHours"),
                row.get("OpeningHoursNote"),
            ),
            "is_inside_venue": False,
            "key_is_derived": False,
            "retrieved_at": retrieved_at,
        }

        # Add the toilet when the source marks it as accessible.
        if accessible:
            key_required = _flag(row.get("KeyRequired"))
            mlak = _flag(row.get("MLAK24"))
            payment = _flag(row.get("PaymentRequired"))

            amenity_rows.append(
                {
                    **base,
                    "amenity_id": f"{SOURCE_ID}:{facility_id}:toilet",
                    "kind": KIND_TOILET,
                    "key_required": key_required,
                    "mlak_24h": mlak,
                    "payment_required": payment,
                    "access_note": _clean(row.get("AccessNote")),
                    "facility_note": _clean(row.get("ToiletNote")),
                    "ambulant": _flag(row.get("Ambulant")),
                    "left_hand_transfer": _flag(row.get("LHTransfer")),
                    "right_hand_transfer": _flag(row.get("RHTransfer")),
                    "accessible_parking_on_site": _flag(row.get("ParkingAccessible")),
                    "changing_places": None,
                    "byo_sling": None,
                    "has_shower": None,
                }
            )

            toilets += 1

            if key_required:
                conditions["key required"] += 1

            if mlak:
                conditions["MLAK 24 hour"] += 1

            if payment:
                conditions["payment required"] += 1

            if base["opening_hours"]:
                conditions["opening hours stated"] += 1

        # Add a change facility separately when one is available.
        if has_change:
            amenity_rows.append(
                {
                    **base,
                    "amenity_id": f"{SOURCE_ID}:{facility_id}:change",
                    "kind": KIND_CHANGE,
                    "key_required": _flag(row.get("KeyRequired")),
                    "mlak_24h": _flag(row.get("ACMLAK")),
                    "payment_required": _flag(row.get("PaymentRequired")),
                    "access_note": _clean(row.get("AccessNote")),
                    "facility_note": _notes(
                        row.get("AdultChangeNote"),
                        row.get("ToiletNote"),
                    ),
                    "ambulant": None,
                    "left_hand_transfer": None,
                    "right_hand_transfer": None,
                    "accessible_parking_on_site": _flag(row.get("ParkingAccessible")),
                    "changing_places": bool(changing),
                    "byo_sling": _flag(row.get("BYOSling")),
                    "has_shower": _flag(row.get("ACShower")),
                }
            )

            changes += 1

            if changing:
                changing_places += 1

    amenities = pd.DataFrame(amenity_rows)
    quarantine = pd.DataFrame(quarantine_rows)

    in_state = stats["rows_in_state"] or 1

    stats["toilets_emitted"] = toilets
    stats["change_emitted"] = changes
    stats["changing_places"] = changing_places
    stats["conditions"] = conditions
    stats["quarantine_rate_pct"] = round(
        100 * len(quarantine) / in_state,
        2,
    )

    # Check that the generated IDs are still unique.
    if len(amenities):
        duplicate_ids = int(amenities["amenity_id"].duplicated().sum())

        if duplicate_ids:
            raise ValueError(
                f"DS-02 produced {duplicate_ids} duplicate amenity_id values, "
                "which would break the idempotent upsert."
            )

    return TransformResult(
        amenities=amenities,
        quarantine=quarantine,
        stats=stats,
    )

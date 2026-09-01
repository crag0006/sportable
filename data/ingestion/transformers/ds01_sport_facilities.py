"""
ingestion/transformers/ds01_sport_facilities.py

Transforms the raw DS-01 data into normalised rows.

This file only handles the transformation. It does not do any database work,
file reading or network requests. The raw dataframe and other required values
are passed into the functions, and the transformed data is returned.

The main rules here come from the profiling notebook.

Grain
    The source has one row for each facility and sport combination. There are
    9,590 rows in the source but only 5,000 facilities. The data therefore
    needs to be collapsed to one venue per Facility ID.

Conflicts
    Some venue fields have different values across rows belonging to the same
    facility. We don't try to choose one of the values. If the rows disagree,
    the value is treated as unpublished instead.

Truncation
    Facility Features can be limited to 255 characters. If a value reaches
    this length, we cannot assume that a missing token means the feature is
    not available. The list may simply have been cut off.

Placeholders
    Some cells contain values such as "Same as above". These are spreadsheet
    placeholders rather than actual data, so they are converted to null.

Coordinates
    Facilities without valid coordinates are quarantined. They are not
    geocoded here because this transformer does not have access to a geocoder.
    Geocoding can be handled separately later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SOURCE_ID = "DS-01"
SHEET_NAME = "wholeIFMD"

# Maximum length used by the publisher for this field.
# If a value is exactly this length it may have been truncated.
TRUNCATION_LIMIT = 255

# These values are treated as missing values rather than actual data.
PLACEHOLDER_VALUES = {"same as above", "as above", "n/a", "na", "nil", "none", "-", "unknown"}

# Only these Facility Features are used for the access chain.
ACCESS_TOKENS = {
    "onsite_accessible_toilet": "Toilets (Disabled)",
    "onsite_accessible_parking": "Parking Bay(s) for the disabled",
}

# Columns that are not needed in the final venue data.
DROPPED_COLUMNS = [
    "Age of Facility",
    "Condition of Facility",
    "Facility Upgrade Age",
    "Spectator numbers for seating/shelter",
    "Melway Ref",
    "VicRoads Ref",
    "MelwaysVicRoadsRef",
    "Facility_AutoNumber",
    "Facility ID.1",
    "FaciltySportPlayedID",
    "CFA Safer Place?",
]

# These columns describe the sports at a facility rather than the facility
# itself. They are stored as child rows.
SPORT_COLUMNS = ["Sports Played", "Number of Field/Courts", "Field/Surface Type"]

CONFIRMED = "confirmed"
NOT_AVAILABLE = "not_available"
NO_INFO = "no_published_information"


@dataclass
class TransformResult:
    """Stores the transformed data and some basic statistics."""

    venues: pd.DataFrame
    venue_sports: pd.DataFrame
    quarantine: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats
        lines = [
            f"DS-01 transform",
            f"  rows read                {s.get('rows_read', 0):,}",
            f"  facilities in source     {s.get('facilities_in_source', 0):,}",
            f"  facilities in scope      {s.get('facilities_in_scope', 0):,}",
            f"  venues loaded            {len(self.venues):,}",
            f"  sport rows loaded        {len(self.venue_sports):,}",
            f"  quarantined              {len(self.quarantine):,}"
            f"  ({s.get('quarantine_rate_pct', 0)}% of in-scope facilities)",
        ]
        if len(self.quarantine):
            lines.append("  quarantine by reason")
            for reason, n in self.quarantine["reason"].value_counts().items():
                lines.append(f"    {reason:<24} {n:,}")
        for col in ("onsite_accessible_toilet", "onsite_accessible_parking"):
            if col in self.venues.columns:
                lines.append(f"  {col}")
                for status, n in self.venues[col].value_counts().items():
                    lines.append(f"    {status:<26} {n:,}")
        return "\n".join(lines)

# Helpers


# Some suburb values have a state abbreviation at the end, for example
# "EAST IVANHOE VIC". Remove it before using the suburb name.
_TRAILING_STATE = re.compile(r"[\s,]+(VIC|VICTORIA|NSW|QLD|SA|WA|TAS|NT|ACT)\.?$", re.IGNORECASE)


def _postcode(value: Any) -> str | None:
    """Convert the postcode to a four digit string."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    # Excel can read postcodes as floats when there are null values.
    # For example, 3084 can come through as 3084.0.
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.notna(numeric):
        digits = str(int(numeric))
    else:
        cleaned = _clean(value)
        if cleaned is None:
            return None
        digits = re.sub(r"\D", "", cleaned)

    return digits.zfill(4) if 1 <= len(digits) <= 4 else None


def _suburb(value: Any) -> str | None:
    """Clean the suburb name and remove a state abbreviation if present."""
    cleaned = _clean(value)
    if cleaned is None:
        return None

    cleaned = _TRAILING_STATE.sub("", cleaned).strip(" ,")
    return re.sub(r"\s+", " ", cleaned).title() or None


def _clean(value: Any) -> Any:
    """Clean a value and turn known placeholder values into null."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    s = str(value).strip()
    if not s or s.lower() in PLACEHOLDER_VALUES:
        return None

    return s


def _tokens(value: Any) -> set[str] | None:
    """Split a comma separated value into individual tokens."""
    cleaned = _clean(value)
    if cleaned is None:
        return None

    return {t.strip() for t in cleaned.split(",") if t.strip()}


def _collapse(values: pd.Series) -> tuple[Any, bool]:
    """
    Collapse multiple values for a facility into one value.

    The second value returned tells us whether there was a disagreement
    between the rows.
    """
    distinct = {_clean(v) for v in values}
    distinct.discard(None)

    if not distinct:
        return None, False

    if len(distinct) == 1:
        return distinct.pop(), False

    return None, True


def derive_access_status(features: pd.Series, token: str) -> str:
    """
    Work out the access status for one feature across the facility rows.

    confirmed:
        The token appears in every usable row.

    not_available:
        The token is not present and none of the usable rows were truncated.

    no_published_information:
        There is not enough information to say whether the feature exists.
    """
    usable = [v for v in features if _clean(v) is not None]

    if not usable:
        return NO_INFO

    present = [token in (_tokens(v) or set()) for v in usable]
    truncated = [len(str(v).strip()) >= TRUNCATION_LIMIT for v in usable]

    if all(present):
        return CONFIRMED

    if any(present):
        # Different rows give different information for the same facility.
        # We don't combine the values because that could create a feature
        # that is not consistently reported by the publisher.
        return NO_INFO

    if any(truncated):
        # The value might have been cut before the token appeared.
        return NO_INFO

    return NOT_AVAILABLE


def _reason_for_coordinates(lat: Any, lon: Any) -> str | None:
    """Return a quarantine reason if the coordinate pair cannot be used."""
    lat_n = pd.to_numeric(lat, errors="coerce")
    lon_n = pd.to_numeric(lon, errors="coerce")

    if pd.isna(lat_n) or pd.isna(lon_n):
        return "COORD_MISSING"

    valid_as_given = -90 <= lat_n <= 90 and -180 <= lon_n <= 180
    valid_transposed = -90 <= lon_n <= 90 and -180 <= lat_n <= 180

    if valid_as_given:
        return None

    if valid_transposed:
        # The values look like latitude and longitude have been swapped.
        # Keep this as a separate reason rather than changing the values here.
        return "COORD_TRANSPOSED"

    return "COORD_INVALID"


def _compose_address(row: pd.Series) -> str | None:
    """Use FullAddress where available, otherwise build an address."""
    full = _clean(row.get("FullAddress"))

    if full:
        return re.sub(r"\s+", " ", full)

    parts = [
        _clean(row.get("Street #")),
        _clean(row.get("Street Name")),
        _clean(row.get("Street Type")),
    ]

    street = " ".join(p for p in parts if p)

    tail = ", ".join(
        p for p in (_clean(row.get("Suburb/Town")), _clean(row.get("Pcode"))) if p
    )

    joined = ", ".join(p for p in (street, tail) if p)
    return joined or None


# Transform


def transform(
    raw: pd.DataFrame,
    in_scope_lgas: set[str],
    normalise_lga,
    load_run_id: int | None = None,
    retrieved_at: Any = None,
) -> TransformResult:
    """
    Transform the raw DS-01 data into venues, sports and quarantine rows.

    LGA names are used here to filter the data to the required scope.
    The actual spatial check against the boundary layer happens later in the
    loader because the geometry is not available in this function.
    """

    stats: dict[str, Any] = {"rows_read": len(raw)}
    df = raw.copy()

    missing = [
        c for c in ("Facility ID", "Facility Name", "LGA Name")
        if c not in df.columns
    ]

    if missing:
        raise ValueError(f"DS-01 sheet is missing required columns: {missing}")

    df = df.drop(columns=[c for c in DROPPED_COLUMNS if c in df.columns])
    stats["facilities_in_source"] = int(df["Facility ID"].nunique())

    df["lga_normalised"] = df["LGA Name"].map(normalise_lga)
    df = df[df["lga_normalised"].isin(in_scope_lgas)].copy()
    stats["facilities_in_scope"] = int(df["Facility ID"].nunique())

    venue_rows: list[dict] = []
    sport_rows: list[dict] = []
    quarantine_rows: list[dict] = []
    conflicts: dict[str, int] = {}

    for facility_id, group in df.groupby("Facility ID", sort=True):
        first = group.iloc[0]

        lat, conflict_lat = (
            _collapse(group["Latitude"])
            if "Latitude" in group
            else (None, False)
        )

        lon, conflict_lon = (
            _collapse(group["Longitude"])
            if "Longitude" in group
            else (None, False)
        )

        reason = _reason_for_coordinates(lat, lon)

        if conflict_lat or conflict_lon:
            reason = reason or "SCHEMA_VIOLATION"

        if reason is not None:
            quarantine_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "natural_key": str(facility_id),
                    "reason": reason,
                    "detail": (
                        "the publisher's rows disagree about this facility's position"
                        if (conflict_lat or conflict_lon)
                        else f"latitude={lat!r} longitude={lon!r}"
                    ),
                    "payload": {
                        "facility_id": str(facility_id),
                        "name": _clean(first.get("Facility Name")),
                        "lga": _clean(first.get("LGA Name")),
                        "full_address": _compose_address(first),
                        "latitude": lat,
                        "longitude": lon,
                    },
                }
            )
            continue

        venue: dict[str, Any] = {
            "venue_id": str(facility_id),
            "source_id": SOURCE_ID,
            "load_run_id": load_run_id,
            "name": _clean(first.get("Facility Name")),
            "full_address": _compose_address(first),
            "suburb_name": _suburb(first.get("Suburb/Town")),
            "postcode": _postcode(first.get("Pcode")),
            "lga_name": _clean(first.get("LGA Name")),
            "lga_normalised": first.get("lga_normalised"),
            "latitude": float(lat),
            "longitude": float(lon),
            "retrieved_at": retrieved_at,
        }

        # These fields describe the venue. If multiple rows have different
        # values, leave the field empty rather than choosing one arbitrarily.
        for column, target in (
            ("Facility Ownership", "ownership"),
            ("Facility Purpose", "purpose"),
            ("Changerooms", "changeroom_description"),
        ):
            if column in group.columns:
                value, disagreed = _collapse(group[column])
                venue[target] = value

                if disagreed:
                    conflicts[column] = conflicts.get(column, 0) + 1
            else:
                venue[target] = None

        # Access fields use three possible states instead of normal null values.
        features = (
            group["Facility Features"]
            if "Facility Features" in group.columns
            else pd.Series([], dtype=object)
        )

        for target, token in ACCESS_TOKENS.items():
            venue[target] = derive_access_status(features, token)

        venue_rows.append(venue)

        # Store sports as child rows. If the same sport and surface are listed
        # more than once, only keep one copy.
        seen: set[tuple] = set()

        for _, r in group.iterrows():
            sport = _clean(r.get("Sports Played"))

            if sport is None:
                continue

            surface = _clean(r.get("Field/Surface Type"))
            courts = pd.to_numeric(
                r.get("Number of Field/Courts"),
                errors="coerce",
            )

            key = (sport, surface)

            if key in seen:
                continue

            seen.add(key)

            sport_rows.append(
                {
                    "venue_id": str(facility_id),
                    "sport": sport,
                    "court_count": None if pd.isna(courts) else int(courts),
                    "surface_type": surface,
                }
            )

    venues = pd.DataFrame(venue_rows)
    venue_sports = pd.DataFrame(sport_rows)

    if len(venue_sports):
        venue_sports["court_count"] = venue_sports["court_count"].astype("Int64")

    quarantine = pd.DataFrame(quarantine_rows)

    in_scope = stats["facilities_in_scope"] or 1

    stats["quarantine_rate_pct"] = round(
        100 * len(quarantine) / in_scope,
        2,
    )

    stats["collapse_conflicts"] = conflicts
    stats["venues_loaded"] = len(venues)
    stats["sport_rows_loaded"] = len(venue_sports)
    stats["distinct_sports"] = (
        int(venue_sports["sport"].nunique())
        if len(venue_sports)
        else 0
    )

    return TransformResult(
        venues=venues,
        venue_sports=venue_sports,
        quarantine=quarantine,
        stats=stats,
    )
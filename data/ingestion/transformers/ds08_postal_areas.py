"""
ingestion/transformers/ds08_postal_areas.py

Transforms the DS-08 ABS Postal Areas shapefile into postal_area rows.

DS-08 exists for one reason. The search box accepts a postcode and the results
header names the point distances were measured from, so a typed 3000 has to
resolve to a coordinate. DS-07 is ABS Suburbs and Localities and publishes no
postcode field, so before this source there was nothing in the register that
could do it.

This layer never touches a facility status. It resolves a typed string to a
search point and nothing else, which is why it carries no accessibility
attributes and supplies no facility types.

The caller passes in a GeoDataFrame already read from the shapefile. Geometry
is reprojected to EPSG:7844 by the caller if the file declares anything else;
the ABS GDA2020 files already declare 7844, so in practice nothing is
reprojected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

SOURCE_ID = "DS-08"

CODE_COLUMN = "POA_CODE21"
NAME_COLUMN = "POA_NAME21"

# The ABS ships non-spatial special purpose codes in every ASGS layer. They
# carry a null geometry and are not real places, so they are excluded before the
# gazetteer is built rather than loaded and filtered later.
#
# Listed exactly rather than matched on a prefix. A prefix rule on "9" would
# also drop every real Queensland postcode in the 9000 range, which is not a
# problem for a Melbourne product today and would be an invisible one for
# anybody who reuses this layer.
SPECIAL_PURPOSE_CODES = {"9494", "9797", "9999", "ZZZZ"}


@dataclass
class TransformResult:
    postal_areas: pd.DataFrame
    quarantine: pd.DataFrame
    stats: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        s = self.stats

        return "\n".join(
            [
                "DS-08 transform",
                f"  features read            {s.get('features_read', 0):,}",
                f"  special purpose codes    {s.get('special_purpose', 0):,}",
                f"  null geometry            {s.get('null_geometry', 0):,}",
                f"  postal areas loaded      {len(self.postal_areas):,}",
                f"  quarantined              {len(self.quarantine):,}",
            ]
        )


def _clean(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    s = str(value).strip()

    if not s or s.lower() in {"nan", "none", "null"}:
        return None

    return s


def transform(
    features,
    load_run_id: int | None = None,
    retrieved_at: Any = None,
) -> TransformResult:
    """Convert the DS-08 shapefile into postal_area rows.

    features is a GeoDataFrame. Only the code, the name and the geometry are
    kept; the ABS area column is not carried because nothing uses it.
    """

    stats: dict[str, Any] = {"features_read": len(features)}

    missing = [
        c for c in (CODE_COLUMN, NAME_COLUMN) if c not in features.columns
    ]

    if missing:
        raise ValueError(
            f"DS-08 shapefile is missing required columns: {missing}. "
            "Check the ASGS vintage before changing this contract."
        )

    rows: list[dict] = []
    quarantine_rows: list[dict] = []

    special = 0
    null_geometry = 0

    for _, feature in features.iterrows():
        code = _clean(feature.get(CODE_COLUMN))
        name = _clean(feature.get(NAME_COLUMN))

        if code is None:
            quarantine_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "natural_key": None,
                    "reason": "REQUIRED_FIELD_NULL",
                    "detail": f"{CODE_COLUMN} is null",
                    "payload": {"name": name},
                }
            )
            continue

        if code.upper() in SPECIAL_PURPOSE_CODES:
            special += 1
            continue

        geometry = feature.get("geometry")

        if geometry is None or geometry.is_empty:
            null_geometry += 1
            quarantine_rows.append(
                {
                    "source_id": SOURCE_ID,
                    "load_run_id": load_run_id,
                    "natural_key": code,
                    "reason": "COORD_MISSING",
                    "detail": "feature carries no geometry",
                    "payload": {"code": code, "name": name},
                }
            )
            continue

        rows.append(
            {
                "poa_code": code,
                "poa_name": name or code,
                "source_id": SOURCE_ID,
                "load_run_id": load_run_id,
                "wkt": geometry.wkt,
                "retrieved_at": retrieved_at,
            }
        )

    postal_areas = pd.DataFrame(rows)
    quarantine = pd.DataFrame(quarantine_rows)

    stats["special_purpose"] = special
    stats["null_geometry"] = null_geometry

    if len(postal_areas):
        duplicated = int(postal_areas["poa_code"].duplicated().sum())

        if duplicated:
            raise ValueError(
                f"DS-08 has {duplicated} duplicate POA codes. The natural key "
                "contract is broken and the load must not proceed."
            )

    return TransformResult(
        postal_areas=postal_areas,
        quarantine=quarantine,
        stats=stats,
    )

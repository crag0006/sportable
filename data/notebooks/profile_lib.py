"""
profile_lib.py - shared helper functions for the SportAble Melbourne
profiling notebooks.

This file contains the common functions used by the profiling notebooks.
The notebooks work with the raw files that were already downloaded into
the _raw folder.

The main things handled here are:
- finding the correct raw file
- checking the file hash against the manifest
- storing profiling results
- recording checks, limitations and contract notes

The raw data is only read here. Nothing in the raw folder is changed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Paths

# The notebooks are inside SportAble/data/notebooks/ and the raw data
# is stored in SportAble/_raw/.
# SPORTABLE_ROOT can be used if the project is stored somewhere else.
_DEFAULT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.environ.get("SPORTABLE_ROOT", _DEFAULT_ROOT)).resolve()
RAW_ROOT = PROJECT_ROOT / "_raw"
MANIFEST_ROOT = RAW_ROOT / "_manifests"
PROFILE_ROOT = PROJECT_ROOT / "_profiles"

# Dataset ID to the folder name used in the raw zone.
# These names match the folders created by fetch_local.py.
# A value of None means the source lands nothing, because it is a live API.
DATASET_DIRS = {
    "DS-01": "sport_facilities",
    "DS-02": "public_toilets",
    "DS-03": "ptv_gtfs",
    "DS-04": "accessible_parking",
    "DS-05": None,  # OpenRouteService is a live API, so nothing is stored here.
    "DS-06": "lga_boundaries",
    "DS-07": "suburb_boundaries",
}

# Dataset ids referenced by name in messages and contract notes. Holding them
# here rather than hardcoding the number in a dozen strings means the next
# renumbering is one edit instead of a search across every notebook.
LGA_BOUNDARY_ID = "DS-06"
SUBURB_BOUNDARY_ID = "DS-07"

# Derived from DATASET_DIRS so it cannot drift out of step with it.
LIVE_API_IDS = tuple(k for k, v in DATASET_DIRS.items() if v is None)

# Reference constants

# A rough Greater Melbourne bounding box.
# This is only used as an initial coordinate check.
# The actual geographic filtering is done with the LGA boundary layer during
# Transform, never with this box.
# max_lon widened from 145.90 to 146.25 on 31 Aug 2026: the measured extent of the
# 31-LGA union reaches 146.193, so the original box clipped eastern Yarra Ranges.
GM_BBOX = {
    "min_lon": 144.30,
    "max_lon": 146.25,
    "min_lat": -38.60,
    "max_lat": -37.30,
}

# The 31 LGAs used for Greater Melbourne.
# This is mainly used for checking names and reporting.
# The boundary files are still used for the actual spatial filtering.
GREATER_MELBOURNE_LGAS = [
    "Banyule", "Bayside", "Boroondara", "Brimbank", "Cardinia", "Casey",
    "Darebin", "Frankston", "Glen Eira", "Greater Dandenong", "Hobsons Bay",
    "Hume", "Kingston", "Knox", "Manningham", "Maribyrnong", "Maroondah",
    "Melbourne", "Melton", "Merri-bek", "Monash", "Moonee Valley",
    "Mornington Peninsula", "Nillumbik", "Port Phillip", "Stonnington",
    "Whitehorse", "Whittlesea", "Wyndham", "Yarra", "Yarra Ranges",
]

# Some publisher names are different from the current ABS names.
# Keeping these mappings here makes the changes clear instead of using
# fuzzy matching later.
LGA_NAME_ALIASES = {
    "moreland": "Merri-bek",          # renamed 2022
    "dandenong": "Greater Dandenong",  # publisher drops the qualifier
}

# The ABS disambiguates LGA names that repeat across states, so Victoria's Bayside
# and Kingston are published as "Bayside (Vic.)" and "Kingston (Vic.)". The
# qualifier is part of the published name, not a typo. Councils with a nationally
# unique name carry no qualifier, which is why only these two ever fail to match.
_STATE_QUALIFIER = re.compile(
    r"\s*\((?:vic|nsw|qld|sa|wa|tas|nt|act)\.?\)",
    re.IGNORECASE,
)

_LGA_SUFFIX = re.compile(
    r"\s*\b(city council|shire council|rural city council|borough council|"
    r"city|shire|rural city|borough|council|\(c\)|\(s\)|\(rc\)|\(b\))\b\s*",
    re.IGNORECASE,
)


def normalise_lga(name: Any) -> str | None:
    """Clean up an LGA name and apply the known name changes."""
    if name is None:
        return None
    s = str(name).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = _STATE_QUALIFIER.sub(" ", s)
    s = _LGA_SUFFIX.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return LGA_NAME_ALIASES.get(s.lower(), s)


def synthetic_key(*parts: Any, length: int = 16) -> str:
    """Build a deterministic key for a source that publishes no identifier.

    DS-04 is a map layer whose id attribute is null on every feature, so there
    is no natural key and no publisher-side change detection. Hashing the
    stable attributes of a feature gives a key that is reproducible from raw
    and identical on every run, which is what an idempotent UPSERT needs.

    The key is derived, not published. It changes if the publisher moves a
    point beyond the rounding tolerance used by the caller, and that is a
    limitation to record rather than a defect to work around.
    """
    joined = "|".join("" if p is None else str(p).strip() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


# Raw object resolution


@dataclass
class RawObject:
    dataset_id: str
    dataset_dir: str
    dt: str
    path: Path
    size_bytes: int
    sha256: str
    manifest: dict | None
    sha_matches_manifest: bool | None

    def __repr__(self) -> str:
        m = {True: "match", False: "MISMATCH", None: "not in manifest"}[
            self.sha_matches_manifest
        ]
        return (
            f"RawObject({self.dataset_id} dt={self.dt} "
            f"{self.path.name} {self.size_bytes:,}B sha={self.sha256[:12]}… [{m}])"
        )


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    """Calculate the SHA-256 hash of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _deep_find(obj: Any, keys: set[str]) -> Any:
    """Find the first matching value inside a nested dictionary or list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in keys and isinstance(v, (str, int, float)):
                return v
        for v in obj.values():
            found = _deep_find(v, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _deep_find(v, keys)
            if found is not None:
                return found
    return None


def _load_manifest(dataset_dir: str, dt: str) -> dict | None:
    """Load the manifest for a dataset partition."""
    base = MANIFEST_ROOT / dataset_dir
    candidates: list[Path] = []
    run_dir = base / f"dt={dt}"
    if run_dir.is_dir():
        candidates += sorted(run_dir.glob("run-*.json"), reverse=True)
    latest = base / "latest.json"
    if latest.is_file():
        candidates.append(latest)
    for c in candidates:
        try:
            return json.loads(c.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def resolve(dataset_id: str, dt: str | None = None) -> RawObject:
    """
    Find the raw object for a dataset.

    If no date is provided, the newest dt partition is used. The file hash
    is recalculated and compared with the manifest when a hash is available.
    """
    if dataset_id not in DATASET_DIRS:
        raise ValueError(
            f"{dataset_id} is not in the register. Known ids: "
            f"{', '.join(sorted(DATASET_DIRS))}"
        )

    dataset_dir = DATASET_DIRS[dataset_id]
    if dataset_dir is None:
        raise ValueError(
            f"{dataset_id} has no raw zone folder. It is a live API and lands "
            f"nothing, so it has no Stage 2 profile. Live sources: "
            f"{', '.join(LIVE_API_IDS)}"
        )

    base = RAW_ROOT / dataset_dir
    if not base.is_dir():
        raise FileNotFoundError(
            f"No raw zone folder at {base}. Run scripts/fetch_local.py {dataset_id}."
        )

    partitions = sorted(p for p in base.glob("dt=*") if p.is_dir())
    if not partitions:
        raise FileNotFoundError(f"No dt= partition under {base}.")
    part = (base / f"dt={dt}") if dt else partitions[-1]
    if not part.is_dir():
        raise FileNotFoundError(f"No partition {part}.")

    files = [f for f in sorted(part.iterdir()) if f.is_file()]
    if len(files) != 1:
        raise RuntimeError(
            f"Expected exactly one object in {part}, found {len(files)}: "
            f"{[f.name for f in files]}"
        )
    obj = files[0]

    resolved_dt = part.name.split("=", 1)[1]
    manifest = _load_manifest(dataset_dir, resolved_dt)
    digest = _sha256(obj)
    declared = _deep_find(
        manifest or {},
        {"sha256", "sha_256", "sha256_hex", "checksum", "hash"},
    )
    matches = None
    if isinstance(declared, str) and len(declared) == 64:
        matches = declared.lower() == digest

    return RawObject(
        dataset_id=dataset_id,
        dataset_dir=dataset_dir,
        dt=resolved_dt,
        path=obj,
        size_bytes=obj.stat().st_size,
        sha256=digest,
        manifest=manifest,
        sha_matches_manifest=matches,
    )


def zip_inventory(raw: RawObject) -> "list[dict]":
    """List the files stored inside a ZIP dataset."""
    with zipfile.ZipFile(raw.path) as z:
        return [
            {
                "name": i.filename,
                "size_bytes": i.file_size,
                "compressed_bytes": i.compress_size,
            }
            for i in z.infolist()
            if not i.is_dir()
        ]


# Profile record

VERDICTS = {"pass", "warn", "fail", "info"}


@dataclass
class Profile:
    """Stores the profiling results for one dataset."""

    raw: RawObject
    title: str
    observations: dict[str, Any] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    contract_notes: list[str] = field(default_factory=list)

    # recording 

    def observe(self, key: str, value: Any, note: str | None = None) -> Any:
        """Store an observation that is useful for the report."""
        self.observations[key] = {"value": _jsonable(value), "note": note}
        return value

    def check(self, key: str, verdict: str, detail: str, value: Any = None) -> str:
        """Store a check with a pass, warn, fail or info result."""
        if verdict not in VERDICTS:
            raise ValueError(f"verdict must be one of {sorted(VERDICTS)}")
        self.checks.append(
            {
                "key": key,
                "verdict": verdict,
                "detail": detail,
                "value": _jsonable(value),
            }
        )
        return verdict

    def limitation(self, text: str) -> None:
        """Add a known limitation for the dataset."""
        self.limitations.append(text)

    def contract(self, text: str) -> None:
        """Add a rule that needs to be considered during Transform."""
        self.contract_notes.append(text)

    # output

    @property
    def worst_verdict(self) -> str:
        for v in ("fail", "warn", "pass"):
            if any(c["verdict"] == v for c in self.checks):
                return v
        return "info"

    def to_dict(self) -> dict:
        return {
            "dataset_id": self.raw.dataset_id,
            "title": self.title,
            "dt": self.raw.dt,
            "source_object": self.raw.path.name,
            "size_bytes": self.raw.size_bytes,
            "sha256": self.raw.sha256,
            "sha_matches_manifest": self.raw.sha_matches_manifest,
            "profiled_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "worst_verdict": self.worst_verdict,
            "observations": self.observations,
            "checks": self.checks,
            "limitations": self.limitations,
            "contract_notes": self.contract_notes,
        }

    def save(self, quiet: bool = False) -> Path:
        out_dir = PROFILE_ROOT / f"dt={self.raw.dt}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{self.raw.dataset_id}.json"
        out.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        if not quiet:
            print(self.summary())
            print(f"\nWritten: {out}")
        return out

    def summary(self) -> str:
        mark = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "info": "INFO"}
        manifest_state = {
            True: "hash matches",
            False: "HASH MISMATCH — do not trust this object",
            None: "no hash recorded in manifest",
        }[self.raw.sha_matches_manifest]
        lines = [
            f"{self.raw.dataset_id} — {self.title}",
            f"  object   {self.raw.path.name}  ({self.raw.size_bytes:,} bytes)",
            f"  dt       {self.raw.dt}",
            f"  sha256   {self.raw.sha256}",
            f"  manifest {manifest_state}",
            "",
            f"  Checks ({self.worst_verdict.upper()} overall)",
        ]
        for c in self.checks:
            lines.append(f"    [{mark[c['verdict']]}] {c['key']}: {c['detail']}")
        if self.limitations:
            lines.append("")
            lines.append("  For the known-limitation register")
            for t in self.limitations:
                lines.append(f"    - {t}")
        if self.contract_notes:
            lines.append("")
            lines.append("  For the Stage 3 column contract")
            for t in self.contract_notes:
                lines.append(f"    - {t}")
        return "\n".join(lines)


def _jsonable(v: Any) -> Any:
    """Convert pandas and numpy values into values that JSON can store."""
    try:
        import numpy as np

        if isinstance(v, np.generic):
            return v.item()
    except Exception:
        pass
    try:
        import pandas as pd

        if isinstance(v, pd.Series):
            return {str(k): _jsonable(x) for k, x in v.items()}
        if isinstance(v, pd.DataFrame):
            return json.loads(v.to_json(orient="records"))
        if v is pd.NaT or (isinstance(v, float) and pd.isna(v)):
            return None
    except Exception:
        pass
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    if isinstance(v, Path):
        return str(v)
    return v


# Shared checks


def check_coordinates(
    p: Profile,
    df,
    lat_col: str,
    lon_col: str,
    label: str = "rows",
) -> dict:
    """Check missing, invalid and Greater Melbourne coordinates."""
    import pandas as pd

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    total = len(df)
    null = int((lat.isna() | lon.isna()).sum())
    invalid = int(
        (
            ((lat < -90) | (lat > 90) | (lon < -180) | (lon > 180))
            & lat.notna()
            & lon.notna()
        ).sum()
    )
    in_bbox = (
        lat.between(GM_BBOX["min_lat"], GM_BBOX["max_lat"])
        & lon.between(GM_BBOX["min_lon"], GM_BBOX["max_lon"])
    )
    n_in = int(in_bbox.sum())

    # If the coordinates are invalid in their current order but become valid
    # when swapped, treat this as a possible column-order issue. We record it
    # separately instead of silently changing the values.
    as_given_valid = lat.between(-90, 90) & lon.between(-180, 180)
    transposed_valid = lon.between(-90, 90) & lat.between(-180, 180)
    swapped = int(
        (~as_given_valid & transposed_valid & lat.notna() & lon.notna()).sum()
    )

    stats = {
        "total": total,
        "null_coords": null,
        "out_of_range": invalid,
        "likely_swapped_lat_lon": swapped,
        "inside_gm_bbox": n_in,
        "outside_gm_bbox": total - null - n_in,
        "pct_inside_gm_bbox": round(100 * n_in / total, 2) if total else None,
    }
    p.observe("coordinates", stats)

    p.check(
        "coords_present",
        "pass" if null == 0 else "warn",
        f"{null:,} of {total:,} {label} have a null coordinate"
        + ("" if null == 0 else " — these quarantine, they are never geocoded"),
        null,
    )
    p.check(
        "coords_in_range",
        "pass" if invalid == 0 else "fail",
        f"{invalid:,} {label} have a coordinate outside valid lat/lon range",
        invalid,
    )
    p.check(
        "coords_not_transposed",
        "pass" if swapped == 0 else "warn",
        (
            f"no {label} have latitude and longitude in the wrong columns"
            if swapped == 0
            else f"{swapped:,} {label} are invalid as given but valid when transposed — "
            "the publisher has swapped the columns for these rows; they are quarantined "
            "with a distinct reason code rather than silently corrected"
        ),
        swapped,
    )
    p.check(
        "coords_greater_melbourne",
        "info",
        f"{n_in:,} of {total:,} {label} fall inside the Greater Melbourne bounding box "
        f"({stats['pct_inside_gm_bbox']}%) — coarse screen only, the clip is spatial "
        f"against {LGA_BOUNDARY_ID}",
        n_in,
    )
    return stats


def truncation_scan(
    series,
    name: str,
    p: Profile | None = None,
) -> dict:
    """Look for signs that a text column has been cut at a fixed length."""
    import pandas as pd

    s = series.dropna().astype(str)
    if s.empty:
        return {
            "column": name,
            "truncated": False,
            "reason": "column is entirely null",
        }

    lengths = s.str.len()
    max_len = int(lengths.max())
    at_max = int((lengths == max_len).sum())
    share = at_max / len(s)
    truncated = bool(
        max_len in (255, 254, 256, 100, 128, 50)
        and at_max > 1
        and share > 0.01
    )

    result = {
        "column": name,
        "non_null": int(len(s)),
        "max_length": max_len,
        "rows_at_max_length": at_max,
        "share_at_max_length": round(share, 4),
        "truncated": truncated,
    }

    if p is not None:
        p.observe(f"truncation_{name}", result)
        p.check(
            f"truncation_{name}",
            "warn" if truncated else "pass",
            (
                f"{name} is cut at {max_len} characters, {at_max:,} rows sit at exactly that "
                f"length — token presence is evidence, token absence is not"
                if truncated
                else f"{name} shows no fixed-width truncation (max {max_len} chars)"
            ),
            result,
        )

    return result


def token_counts(
    series,
    sep: str = ",",
    min_count: int = 1,
) -> "pd.DataFrame":
    """Split a delimited column and count how often each value appears."""
    import pandas as pd

    exploded = (
        series.dropna().astype(str).str.split(sep).explode().str.strip()
    )
    exploded = exploded[exploded.ne("")]
    vc = exploded.value_counts()
    vc = vc[vc >= min_count]
    return vc.rename_axis("token").reset_index(name="rows")


def fragment_report(
    tokens: "pd.DataFrame",
    token_col: str = "token",
) -> "pd.DataFrame":
    """
    Find tokens that look like shortened versions of longer tokens.

    These may be caused by truncated lists, so they should not be treated
    as separate categories.
    """
    import pandas as pd

    vals = sorted(tokens[token_col].astype(str).tolist(), key=len, reverse=True)
    frag = []

    for t in vals:
        if any(other != t and other.startswith(t) for other in vals):
            frag.append(t)

    out = tokens[tokens[token_col].isin(frag)].copy()
    out["likely_truncation_fragment"] = True
    return out.sort_values("rows", ascending=False)


def load_profiles(dt: str | None = None) -> dict[str, dict]:
    """Load the profiles created for a dt partition."""
    parts = sorted(p for p in PROFILE_ROOT.glob("dt=*") if p.is_dir())
    if not parts:
        raise FileNotFoundError(
            f"No profiles under {PROFILE_ROOT}. Run notebooks 01-05 first."
        )

    part = (PROFILE_ROOT / f"dt={dt}") if dt else parts[-1]
    out = {}

    for f in sorted(part.glob("DS-*.json")):
        out[f.stem] = json.loads(f.read_text(encoding="utf-8"))

    return out
# Profiling notebooks

Stage 2 of the pipeline lands immutable raw objects. These notebooks sit between
Stage 2 and Stage 3: they establish what is actually in each landed object so the
column contracts are written from measurement rather than from assumption.

## Placement

```
SportAble/
  _raw/                     <- landed objects, read only
  _profiles/dt=YYYY-MM-DD/  <- written by these notebooks
  _reference/               <- derived clip layer, written by notebook 05
  data/
    scripts/fetch_local.py
    notebooks/              <- this folder
```

`profile_lib.py` resolves the project root as two levels above itself. If your
layout differs, set `SPORTABLE_ROOT` before importing.

## Running

```
uv add jupyter pandas openpyxl tabulate
uv add geopandas          # notebook 05 only
uv run jupyter lab
```

Run in order. Notebooks 01 to 05 each emit `_profiles/dt=<partition>/DS-XX.json`.
Notebook 06 reads them all and writes `coverage_assessment.md`.

| Notebook | Datasets | Settles |
|---|---|---|
| 01 | DS-01 | Grain, Victorian vs Greater Melbourne extent, field truncation, tri-state derivation |
| 02 | DS-02 | National vs Victorian extent, boolean semantics, access conditions on accessible toilets |
| 03 | DS-03 | Per-mode feed structure, `wheelchair_boarding` and `wheelchair_accessible` distributions, feed validity window |
| 04 | DS-04, DS-05 | Six-slot restriction shape, dedicated bay vs permit extension, the `bayid` join, single-LGA coverage |
| 05 | DS-07, DS-08 | Declared CRS, presence of all 31 Greater Melbourne LGAs, the derived clip layer |
| 06 | all | Consolidated findings, draft known-limitation register, column contract rules |

DS-06 is OpenRouteService. It is a live API and lands nothing in the raw zone, so it
has no profiling notebook. Its coverage question is a rate-limit and terms question,
handled in the source register.

## What a profile is

Each profile record carries the dataset id, the `dt` partition, the SHA-256
recomputed from the bytes on disk, and the UTC time it was produced. A profile that
cannot name the hash of what it profiled is not reproducible evidence, so the hash is
recomputed rather than copied from the manifest, and compared against the manifest
where one records it.

Findings are typed:

- **observations** — a number or breakdown worth reporting
- **checks** — `pass` / `warn` / `fail` / `info`; only checks gate
- **limitations** — entries for the known-limitation register in DMP section 10.3
- **contract notes** — rules the Stage 3 transform has to implement

The notebooks never write to `_raw` and never fill a gap. Where a source does not
say, the profile records that it does not say.

## Reading a verdict

`fail` means the Stage 3 contract for that feed cannot be written until it is
resolved. `warn` means the contract has to carry a specific rule to handle it, and
that rule is in the contract notes. `info` is a coverage figure for the quality
report, not a defect.

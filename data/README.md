# Data — SportAble Melbourne

Owner: Data team (2 members). The Infra/Platform engineer owns the AWS
resources that package and run this code, not the code itself.

## Layout

| Path | Purpose |
|---|---|
| `ingestion/extractors/` | One module per source: `vic_sport_rec`, `public_toilets_nptm`, `ptv_gtfs`, `osm`. Pure fetch → raw bytes. |
| `ingestion/transformers/` | Raw payload → normalised rows. No I/O. |
| `ingestion/validators/` | Column contract, null/range/coordinate checks. Rejected rows → quarantine. |
| `ingestion/loaders/` | Idempotent UPSERT into RDS. Safe to replay. |
| `derive/` | `status_builder` (nearest amenity, 250/500/1000 m bands, status derivation), `graph_builder` (Iteration 2). |
| `schemas/` | Column contracts shared by validators and tests. |
| `sql/` | PostGIS bootstrap, spatial index DDL, reference queries. |
| `sources/` | Source registry: name, URL, licence, attribution text, refresh cadence, staleness threshold. |

## Contract with infra

The Lambda handler signature and the S3 key convention are the boundary.

- Raw zone key: `s3://<raw-bucket>/<dataset>/dt=YYYY-MM-DD/<filename>`
- Quarantine key: `s3://<quarantine-bucket>/<dataset>/dt=YYYY-MM-DD/rejected.jsonl`
- Handler entrypoint: `data.ingestion.<stage>.handler(event, context)`

Change the convention and the Terraform in `infra/modules/ingestion` changes with it.

## Non-negotiable rule

**Unknown is never a no.** A facility with no published record is loaded as
`no_published_information`, never as `false`. This is enforced in the loader,
tested in `data/tests`, and is the reason the API can never render a false absence.

## Local setup

`data/` is its own uv project, separate from `backend/`.

```bash
cd data
uv sync                       # installs from uv.lock into data/.venv
uv add pandas                 # add a runtime dependency — commit BOTH files
uv run pytest -q              # unit tests
uv run pytest -q -m integration   # tests needing a live PostGIS container
```

You do **not** need an AWS account to work here. Bring up the local PostGIS
container described in the [repository README](../README.md) and point at it:

```bash
export DATABASE_URL="postgresql://postgres:devpass@localhost:5433/sportable"
```

## What CI checks in this folder

The `Data — lint, type-check, test` job runs ruff, ruff format, mypy and the
unit tests on every pull request. Two things to know:

- **Style is shared with `backend/`** via `ruff.toml` at the repository root —
  line length 100, isort, pyupgrade, bugbear. Run `pre-commit install` once per
  clone and formatting is handled before you commit.
- **mypy here is not strict**, unlike `backend/`. Ingestion code handles
  loosely-typed payloads from third-party portals, and strict mode before the
  column contracts in `schemas/` are settled produces noise rather than signal.
  It tightens once those contracts exist.
- **`notebooks/` is excluded** from linting. Exploratory work is not held to the
  same bar — convert it to a module under `ingestion/` before it ships.
- Tests marked `integration` are **excluded** from the pull-request run. They
  need a real PostGIS container and get their own job once the first loader
  exists.

The job currently skips itself: `data/` holds only placeholder files, and a
pipeline that is red before anyone has written code is one the team learns to
ignore. It starts running on its own with the first `.py` file.

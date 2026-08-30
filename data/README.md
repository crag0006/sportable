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
- Handler entrypoint: `ingestion.<stage>.handler(event, context)`

`data/` is the zip ROOT, which is why the handler path has no leading `data.`
The buckets are `sportable-staging-raw-<account>` and
`sportable-staging-quarantine-<account>`; read them from
`terraform output raw_bucket` rather than typing them.

Change the convention and the Terraform in `infra/modules/ingestion` changes
with it — the load function derives the dataset name by splitting the key on
its first slash, and the S3 notification filters on the same prefix.

### What already runs

| | |
|---|---|
| `ingestion/fetch.py` | Fetches one source, writes it **unmodified** to the raw zone. Runs OUTSIDE the VPC — the only function here with internet access. |
| `ingestion/load.py` | Triggered by the object landing. Reads it, records a manifest under `_manifests/`, and **does not write to the database yet**. Runs INSIDE the VPC. |

The manifest carries `"rows_loaded": 0, "load_status": "pending_loader"` until
a real loader exists. That marker is deliberate: a green invocation must not
imply data reached Postgres.

### What the Data team owns

The transforms, validators and loaders. Two things are worth knowing before you
start:

- **The schedules exist but are DISABLED**, because no source has a URL yet.
  Supply real endpoints in `infra/envs/staging/main.tf` under
  `module.ingestion.sources` and they arm themselves on the next deploy.
- **The load function cannot write to Postgres yet** — not because of
  permissions, but because `psycopg` is not in the deployment package and this
  project has no build step that installs dependencies into a Lambda zip.
  `archive_file` zips a directory; it cannot run pip. The same gap blocks the
  Alembic migration Lambda, and one build step solves both.

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

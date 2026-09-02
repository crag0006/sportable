# SportAble Melbourne

Helping wheelchair users and people with mobility-related access needs in
Greater Melbourne find sports venues that match their access requirements,
and plan an accessible journey to them.

FIT5120 Industry Experience Studio Project · 2026 Semester 2 · EVE Cohort · Team Lumera

## The rule that shapes everything

**Unknown is never a no.** A facility with no published record is shown as
*"No published information — check with the venue"*. It is never rendered,
filtered, sorted or stored as an absence. Every displayed fact carries its
source and the date that source was last updated. There is no combined
accessibility score, because a single rating hides the one failed facility
that decides whether a person can attend.

## Structure

| Path | Owner | Contents |
|---|---|---|
| `backend/` | Backend (2) | FastAPI service, Lambda handlers, Alembic migrations |
| `data/` | Data (2) | Ingestion extractors, transformers, validators, loaders, status derivation |
| `frontend/` | Frontend (2) | React 18 + TypeScript SPA |
| `infra/` | Infra/Platform (1) | Terraform — VPC, RDS, CloudFront, Lambda, ingestion |
| `.github/workflows/` | Infra/Platform (1) | CI, automatic staging deploy, Terraform plan, security scanning |
| `docs/` | All | ADRs, runbooks, API contract, iteration task plans |

## Stack

React 18 · TypeScript · Python 3.12 · FastAPI · PostgreSQL 16 + PostGIS ·
AWS Lambda · API Gateway · S3 · CloudFront · RDS · EventBridge ·
Terraform · GitHub Actions (OIDC)

---

# Getting started

Roughly fifteen minutes. **Step 2 applies to everyone**, whatever your role —
including the Data and Frontend engineers.

## 1. Install what your role needs

| Tool | Who needs it |
|---|---|
| **git**, **pre-commit** | everyone |
| **uv** (Python) | backend, data |
| **Docker Desktop** | backend, data |
| **Node 22+** | frontend |
| **terraform**, **tflint**, **checkov** | infra — see [`infra/README.md`](infra/README.md) |

Python itself is not in the list: `uv` downloads and manages the correct
interpreter (3.12) for you.

**macOS / Linux**

```bash
brew install git uv node
brew install --cask docker
uv tool install pre-commit
```

**Windows (PowerShell)**

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Docker.DockerDesktop -e
uv tool install pre-commit
```

If `winget` is unavailable, download the installers from
[git-scm.com](https://git-scm.com/download/win),
[docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/),
[nodejs.org](https://nodejs.org/) and
[docker.com](https://www.docker.com/products/docker-desktop/).

**Close and reopen your terminal** after installing — `winget` and `brew` both
change `PATH`, and the current shell will not see it.

### Windows: two settings to change first

Do these once, before you clone. Both prevent problems that are confusing to
diagnose afterwards.

```powershell
# 1. Commit LF line endings, whatever your editor writes locally.
#    Without this, Windows commits CRLF, every line of every file shows as
#    changed in the diff, and the pre-commit hooks fight your editor forever.
git config --global core.autocrlf input

# 2. Docker Desktop must use the WSL 2 backend (Settings → General).
#    Install WSL first if you have not:
wsl --install
```

You do **not** need `psql` installed. Every command in this README that uses it
has a Windows equivalent that runs `psql` inside the database container, which
is already there.

## 2. Clone and install the commit hook — everyone

```bash
git clone https://github.com/crag0006/sportable.git
cd sportable
pre-commit install
```

Identical on Windows in PowerShell.

`pre-commit install` writes a git hook that runs the same checks CI runs, every
time you commit. **It is per-clone, not per-repository** — cloning again on
another machine means installing it again.

Sanity check it works:

```bash
pre-commit run --all-files
```

> **Windows:** if this fails with `pre-commit: command not found`, the tool
> directory is not on your `PATH`. Run `uv tool update-shell`, then open a new
> terminal.

Everything should report `Passed` or `Skipped`. If a hook says
`files were modified by this hook`, that is normal: it fixed something, so
`git add` the change and commit again.

What the hooks do and why is documented inline in
[`.pre-commit-config.yaml`](.pre-commit-config.yaml).

## 3. Python — backend and data engineers

`backend/` and `data/` are **two separate uv projects** with their own
dependencies and their own lock files. Set up whichever you work in:

```bash
cd backend          # or: cd data
uv sync             # creates .venv and installs everything from uv.lock
uv run pytest -q    # should pass
```

They are separate on purpose. The API Lambda is latency-sensitive and lives
inside a 250 MB package limit; the ingestion Lambdas want heavier libraries
(pandas, shapely). One shared dependency set would drag those into the API's
package and inflate its cold start for no reason.

**Style rules are shared**, though: `ruff.toml` at the repository root governs
every Python file in the repo, so a line that fails in `data/` fails identically
in `backend/`. Do not add a `[tool.ruff]` section to either `pyproject.toml` —
the nearest config wins, and it would silently override the shared one.

Use `uv run <command>` rather than activating the virtualenv. It guarantees you
are running the locked dependency set, which is exactly what CI runs.

**If you add a dependency**, use `uv add <package>` — never `pip install`.
`uv add` updates both `pyproject.toml` and `uv.lock`, and **`uv.lock` must be
committed**, or CI's `uv sync --frozen` will fail for everyone. Run it in the
project you are working in: a dependency added in `data/` does not appear in
`backend/`, which is the point.

## 4. The local database — backend and data engineers

You do **not** need an AWS account to work on the schema or on queries. A local
PostGIS container matches what RDS will run.

**macOS / Linux**

```bash
docker run --name sportable-pg \
  -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=sportable \
  -p 5433:5432 -d imresamu/postgis:16-3.4

docker exec sportable-pg psql -U postgres -d sportable \
  -c "CREATE EXTENSION IF NOT EXISTS postgis; SELECT postgis_version();"
```

**Windows (PowerShell)**

```powershell
docker run --name sportable-pg `
  -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=sportable `
  -p 5433:5432 -d imresamu/postgis:16-3.4

docker exec sportable-pg psql -U postgres -d sportable `
  -c "CREATE EXTENSION IF NOT EXISTS postgis; SELECT postgis_version();"
```

> PowerShell continues a line with a **backtick** (`` ` ``), not a backslash.
> Copying a `\` from a bash snippet is the most common cause of
> `Missing expression after unary operator` on Windows. If in doubt, put the
> whole command on one line.

Running `psql` through `docker exec` means nobody has to install a Postgres
client. If you would rather have `psql` locally: `brew install libpq &&
brew link --force libpq` on macOS, or add PostgreSQL's `bin` directory to
`PATH` on Windows.

Then apply the migrations:

**macOS / Linux**

```bash
cd backend
export DATABASE_URL="postgresql://postgres:devpass@localhost:5433/sportable"
uv run alembic upgrade head
```

**Windows (PowerShell)**

```powershell
cd backend
$env:DATABASE_URL = "postgresql://postgres:devpass@localhost:5433/sportable"
uv run alembic upgrade head
```

> `$env:NAME = "value"` is PowerShell's `export`. It lasts for the current
> terminal only. In Command Prompt it is `set NAME=value` — but prefer
> PowerShell, since every snippet here assumes it.

Two details that will otherwise cost you an hour:

- **Port 5433, not 5432.** A locally installed PostgreSQL occupies 5432 on both
  macOS and Windows. Using 5433 avoids the clash entirely; change it if 5433 is
  busy for you.
- **`imresamu/postgis`, not `postgis/postgis`.** The official image publishes no
  arm64 build, so on an Apple Silicon Mac it runs emulated and slowly. This
  mirror is the same upstream build with native arm64. On an Intel Mac, on
  Windows, or in CI, either image works — but use the same one everywhere so the
  whole team hits identical behaviour.

Everyday container commands:

```bash
docker stop sportable-pg     # frees the port; data is kept
docker start sportable-pg    # back where you left it
docker rm -f sportable-pg    # delete the container AND its data
```

These are identical on Windows.

### Writing a migration

Migrations live in `backend/migrations/versions/` and are owned by the backend
and data engineers. `alembic.ini` and `migrations/env.py` are infrastructure
plumbing — talk to the infra engineer before changing those.

```bash
cd backend
uv run alembic revision -m "add venue table"    # creates an empty revision
# ... edit the generated file in migrations/versions/ ...
uv run alembic upgrade head                     # apply it
uv run alembic downgrade -1                     # undo it — always test this
```

Test the downgrade. The deploy pipeline runs migrations *before* it shifts
traffic to the new code, so a migration that cannot be reversed is a migration
that cannot be rolled back.

## 5. Frontend engineers

`frontend/` is scaffolding only so far. Once `package.json` exists:

```bash
cd frontend
npm ci
npm run dev
```

The `frontend` job in CI skips itself until `frontend/package.json` appears,
then starts building on every pull request with no change to the workflow.

**You do not need the backend running to start.** T2 provisions API Gateway mock
responses serving the OpenAPI contract's examples, so you get a real URL with
real CORS returning fixture data. Ask the infra engineer for it.

## 6. Infra engineer

See [`infra/README.md`](infra/README.md).

---

# How we work

## Branches

```
main ← release-iteration-{1,2,3} ← dev ← feature/*
```

Branch from `dev`, open a pull request back into `dev`. A push to `dev` deploys
itself to the shared environment. **Nothing is deployed by hand**, and nothing
is committed straight to `dev` or `main`.

```bash
git checkout dev && git pull
git checkout -b feat/short-description
# ... work ...
git add -p && git commit -m "feat: what changed"
git push -u origin feat/short-description
gh pr create --base dev --fill
```

## Before you push

Run what CI runs. Every command below has an exact counterpart in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml):

```bash
cd backend            # or: cd data
uv run ruff check .
uv run ruff format --check .
uv run mypy handlers  # in data/: uv run mypy ingestion derive
uv run pytest tests/unit -q

# everyone, from the repository root
pre-commit run --all-files
```

Identical on Windows — `uv` and `pre-commit` behave the same in PowerShell.

If these pass locally and CI still fails, the cause is almost always an
uncommitted file or a stale `uv.lock`.

## What CI checks

Three jobs run in parallel on every pull request. They are commented in detail
in the workflow file itself.

| Job | Checks |
|---|---|
| **Backend** | ruff lint · ruff format · mypy (strict) · pytest |
| **Data** | ruff lint · ruff format · mypy · pytest (unit only) |
| **Terraform** | `fmt -check` · `validate` · tflint (AWS ruleset) · checkov (security policy) |
| **Frontend** | `npm ci && npm run build` |

Two things worth knowing:

- **CI holds no AWS credentials.** It cannot reach the cloud account at all.
  Deployment is a separate workflow that obtains temporary credentials through
  GitHub OIDC. This separation is deliberate: CI runs pull-request code, so CI
  must not be able to touch AWS.
- **The Terraform and Frontend jobs skip themselves** while those directories
  hold only placeholders, and activate on their own when real files appear.
  A permanently red pipeline is one everybody learns to ignore.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `pre-commit: command not found` | `brew install pre-commit`, then `pre-commit install` |
| Commit aborted, "files were modified by this hook" | Working as intended — a hook fixed something. `git add` and commit again |
| CI fails on `ruff format --check` | You never ran `pre-commit install` in this clone |
| CI fails on `uv sync --frozen` | `uv.lock` is stale or uncommitted. Run `uv sync`, commit `uv.lock` |
| `ModuleNotFoundError: psycopg2` | Use `uv run`, and let `migrations/env.py` build the URL — it pins psycopg 3 |
| `port 5432 already in use` | A local PostgreSQL is running. The container maps to **5433** for this reason |
| `alembic: No database URL available` | `export DATABASE_URL=...` — see step 4 |
| `docker: Cannot connect to the Docker daemon` | Start Docker Desktop. On Windows also check Settings → General → *Use the WSL 2 based engine* |
| Container starts but `psql` refuses the connection | Give it a few seconds: `docker exec sportable-pg pg_isready` |
| **Windows:** `Missing expression after unary operator` | You copied a `\` line continuation from a bash snippet. PowerShell uses a backtick `` ` ``, or put it on one line |
| **Windows:** every file shows as modified, in every diff | CRLF line endings. `git config --global core.autocrlf input`, then re-clone |
| **Windows:** `uv`/`pre-commit` not found right after install | `PATH` was changed by the installer. Open a new terminal; if it persists, `uv tool update-shell` |
| **Windows:** `wsl --install` needed / Docker will not start | Docker Desktop requires the WSL 2 backend. Install WSL, reboot, then start Docker |

## Documents

- [Infrastructure](infra/README.md)
- [Data pipeline](data/README.md)

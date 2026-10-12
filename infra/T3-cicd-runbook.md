# T3 — CI/CD Runbook

**SportAble Melbourne** · FIT5120 · Iteration 1 · Infra/Platform owner: Charan

| | |
|---|---|
| **Task** | T3 — *Make every push to `dev` deploy itself* (13.0 h) |
| **Serves** | Shared Definition of Done — *"deployed to the shared environment and demonstrated from that URL"* |
| **This document** | Part 1 only: **continuous integration, which needs no AWS account** |
| **Written** | 29 Aug 2026 |

---

## Why this task, and why only half of it

T3 splits cleanly in two:

| | Needs AWS? | Status |
|---|---|---|
| **Part 1 — CI** — lint, test, validate on every pull request | **No** | **Do it now** |
| **Part 2 — CD** — state bucket, OIDC provider, deploy role, `deploy-staging.yml` | Yes, and needs `iam:*` | Blocked |

Part 2 is blocked because the IAM user available today (`teammate_deploy`, account
`7256-9985-0301`) carries **PowerUserAccess**, whose policy is `NotAction: ["iam:*", ...]`.
Creating an OIDC provider or a deploy role is denied, and so is `iam:PassRole` — which
would block T2 and T4 as well. Confirmed on 29 Aug 2026: the IAM console returns
`Access denied to iam:ListUsers … no identity-based policy allows the action`.

Part 1 has no such dependency. It runs entirely on GitHub-hosted runners with zero
credentials, and it is the piece that makes every later task safer — a broken migration
or a public S3 bucket gets caught before it reaches the cloud.

**Do not wait for AWS access to start this.**

---

## Prerequisites — verified on this machine, 29 Aug 2026

| | |
|---|---|
| terraform | 1.16.0 (tfenv, `TFENV_CONFIG_DIR=$HOME/.tfenv`) |
| tflint | 0.64.0 (`~/.local/bin`, installed from the verified GitHub release) |
| checkov | 3.3.15 (`uv tool install`) |
| pre-commit | 4.6.2 |
| Docker | 28.5.1, daemon running |
| PostGIS | container `sportable-pg`, **host port 5433**, PG 16.4 / PostGIS 3.4.3 |
| backend venv | `uv sync` complete; `alembic upgrade head` verified end-to-end |

**One outstanding prerequisite:** `gh auth login`. Step 6 needs it.

---

## The seven steps

Work on a branch. Nothing here touches `main` or `dev` directly.

### Step 0 — Branch

```bash
cd "Monash/Studio Project/sportable/sportable-git"
git checkout dev && git pull
git checkout -b feat/ci-pipeline
```

> **Why from `dev`, not `main`:** `dev` is the integration branch the DoD deploys from.
> Branching from `main` means your first PR carries unrelated drift.

---

### Step 1 — `.tflint.hcl` (repo root)

tflint ships only a bundled Terraform ruleset. The rules that matter — invalid instance
types, deprecated RDS arguments, missing required provider fields — live in the **AWS
ruleset plugin**, which has to be declared and downloaded.

```hcl
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.48.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

config {
  call_module_type = "local"
}
```

```bash
tflint --init          # downloads the AWS ruleset
tflint --version       # should now list ruleset.aws
```

> Pin the plugin version. An unpinned ruleset means CI can start failing on a day you
> changed nothing — the single most confusing class of pipeline failure.

---

### Step 2 — `.pre-commit-config.yaml` (repo root)

Pre-commit runs the same checks CI runs, but before the commit exists. The point is not
convenience: it is that **CI never fails on formatting**, so a red check always means a
real problem.

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-merge-conflict
      - id: check-added-large-files
        args: [--maxkb=1024]
      - id: detect-private-key

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.5
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.109.0
    hooks:
      - id: terraform_fmt
```

```bash
pre-commit install                    # writes .git/hooks/pre-commit
pre-commit run --all-files            # first run installs hook envs; expect fixes
```

> `detect-private-key` is not decoration. It is the hook that stops an `.pem` or an AWS
> key reaching a public repository, and this project is explicitly built to hold neither.

---

### Step 3 — Give CI something real to test

`backend/tests/` currently holds only `.gitkeep`. **pytest exits with code 5 when it
collects no tests, which fails the job** — so CI cannot go green until a real test exists.

This also happens to deliver T2's stub-handler sub-task, unblocking the API-Gateway work
from your backend teammate.

**`backend/handlers/stub.py`**

```python
"""Placeholder Lambda handler.

Exists so T2 can wire API Gateway → Lambda before the real application handler
lands. Swapping to the real handler is a one-line change in Terraform.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ANN401, ARG001
    """Return a static health payload in API Gateway HTTP API v2 format."""
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": '{"status":"ok","service":"sportable-api"}',
    }
```

**`backend/tests/unit/test_stub_handler.py`**

```python
import json

from handlers.stub import handler


def test_handler_returns_200():
    response = handler({}, None)
    assert response["statusCode"] == 200


def test_handler_returns_json_status_ok():
    body = json.loads(handler({}, None)["body"])
    assert body["status"] == "ok"
```

Run it:

```bash
cd backend
uv run pytest tests/unit -q
```

---

### Step 4 — `.github/workflows/ci.yml`

```yaml
name: CI

on:
  pull_request:
    branches: [dev, main]
  push:
    branches: [dev]

# A second push cancels the first run on the same branch.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read          # least privilege; CI needs nothing else

jobs:
  backend:
    name: Backend — lint, type-check, test
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v7

      - uses: astral-sh/setup-uv@v10.0.1   # exact tag: astral-sh publishes no moving `v10`
        with:
          enable-cache: true

      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy app handlers
        continue-on-error: true      # strict mode on empty packages; drop this once code lands
      - run: uv run pytest tests/unit -q

  terraform:
    name: Terraform — format, validate, lint, scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: hashicorp/setup-terraform@v4
        with:
          terraform_version: 1.16.0

      - uses: terraform-linters/setup-tflint@v6
        with:
          tflint_version: v0.64.0

      - name: Skip if no Terraform yet
        id: guard
        run: |
          if [ -z "$(find infra -name '*.tf' -print -quit)" ]; then
            echo "found=false" >> "$GITHUB_OUTPUT"
            echo "No .tf files yet — these checks activate when T1 lands."
          else
            echo "found=true" >> "$GITHUB_OUTPUT"
          fi

      - if: steps.guard.outputs.found == 'true'
        run: terraform fmt -check -recursive infra

      - if: steps.guard.outputs.found == 'true'
        working-directory: infra/envs/staging
        run: terraform init -backend=false && terraform validate

      - if: steps.guard.outputs.found == 'true'
        run: tflint --init && tflint --recursive --chdir=infra

      - if: steps.guard.outputs.found == 'true'
        uses: bridgecrewio/checkov-action@v12
        with:
          directory: infra
          framework: terraform
          quiet: true
          soft_fail: false

  frontend:
    name: Frontend — build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - name: Skip until the Frontend team scaffolds the app
        id: guard
        run: |
          if [ -f frontend/package.json ]; then
            echo "found=true" >> "$GITHUB_OUTPUT"
          else
            echo "found=false" >> "$GITHUB_OUTPUT"
            echo "No frontend/package.json yet — this job activates when it appears."
          fi

      - if: steps.guard.outputs.found == 'true'
        uses: actions/setup-node@v7
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - if: steps.guard.outputs.found == 'true'
        working-directory: frontend
        run: npm ci && npm run build
```

#### Why it is shaped this way

- **Three jobs, not one.** They run in parallel, and a red X names the failing area
  without opening a log.
- **The two guards are deliberate.** Neither `infra/**` nor `frontend/**` has content yet.
  Without them the pipeline is red on day one, and a permanently red pipeline is one
  everybody learns to ignore. Each job activates by itself the moment the files appear.
- **`permissions: contents: read`.** The default token is far broader. Part 2 adds
  `id-token: write` to the *deploy* workflow only — and omitting that line is the single
  most common OIDC failure.
- **`uv sync --frozen`** fails if `uv.lock` disagrees with `pyproject.toml`, so CI resolves
  exactly what you resolved locally. This requires `uv.lock` to be committed.
- **`mypy … continue-on-error: true`** is a temporary honesty flag: strict mode on packages
  that hold only `.gitkeep` produces noise, not signal. Remove it the week real code lands.

---

### Step 5 — Prove it locally before pushing

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest tests/unit -q
cd .. && pre-commit run --all-files
```

Everything green locally means the only thing CI can still catch is an environment
difference — which is exactly what you want it there for.

---

### Step 6 — Push and watch it run

```bash
git add .tflint.hcl .pre-commit-config.yaml .github/workflows/ci.yml \
        backend/handlers/stub.py backend/tests/unit/test_stub_handler.py \
        backend/uv.lock backend/migrations/env.py
git commit -m "ci: add pull-request pipeline, tflint and pre-commit config"
git push -u origin feat/ci-pipeline
gh pr create --base dev --fill
gh run watch
```

> `backend/migrations/env.py` carries the psycopg 3 driver fix from 29 Aug — a bare
> `postgresql://` URL resolves to psycopg2, which this project does not install, so every
> `alembic upgrade head` against Postgres failed before it. `backend/uv.lock` was untracked;
> without it `uv sync --frozen` cannot work.

**All commits are made by you, manually. Nothing in this runbook pushes on your behalf.**

---

### Step 7 — Branch protection

Once the PR is green, protect `dev` and `main`. The UI is clearer than the API
for this, because the status-check names have to be picked from a list rather
than typed.

**Settings → Branches → Add branch protection rule**, once for `dev` and once
for `main`:

| Setting | Value | Why |
|---|---|---|
| Branch name pattern | `dev` (then `main`) | One rule per branch |
| Require a pull request before merging | on | Nothing lands unreviewed |
| └ Require approvals | 1 | Professional practice, and visible in the marking |
| Require status checks to pass | on | **See the warning below** |
| └ Required checks | all three CI jobs | Ticking the parent box alone does nothing |
| └ Require branches to be up to date | **off** | On a shared `dev` this forces a re-run every time anyone else merges |
| Require conversation resolution | on | A review comment cannot be silently ignored |
| Allow force pushes | off | Protects history |
| Allow deletions | off | Protects the branch |
| Do not allow bypassing | **off** | Deliberate escape hatch — see below |

> **The trap.** "Require status checks to pass before merging" does nothing on
> its own. You must also add the individual checks in the search box beneath it.
> A rule showing *"No required checks"* enforces nothing at all, while looking
> as though it does.
>
> The search box lists only checks that have reported **within the last seven
> days**, which is why the first CI run has to happen before the rule is
> created. Select the three jobs from the dropdown rather than typing them —
> the names contain em dashes.

> **Renaming a job breaks the rule silently.** The required check is stored as a
> literal string. Rename a job in `ci.yml` and the old name is never reported
> again, so every pull request waits forever on a check that cannot arrive. If
> you rename one, update the branch rule in the same change.

> **Leave "Do not allow bypassing" off.** As repository owner you keep the
> ability to merge without waiting — which is what rescues a demo when the one
> person who could approve is asleep. It is an escape hatch you should almost
> never use, but a shared university project is exactly the situation it exists
> for.

The equivalent via the API, if you prefer:

```bash
gh api -X PUT repos/crag0006/sportable/branches/dev/protection \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": false,
    "contexts": [
      "Backend — lint, type-check, test",
      "Terraform — format, validate, lint, scan",
      "Frontend — build"
    ]
  },
  "required_pull_request_reviews": { "required_approving_review_count": 1 },
  "required_conversation_resolution": true,
  "enforce_admins": false,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

> Protect `dev` *after* the first run is green. Protecting it first means you cannot merge
> the very PR that creates the checks you are requiring.

---

## Definition of done

- [ ] A pull request to `dev` runs three jobs and all three are green
- [ ] `pre-commit run --all-files` passes locally
- [ ] `tflint --version` lists the AWS ruleset
- [ ] A deliberately broken commit (`x=1` with bad formatting) turns CI red
- [ ] `dev` and `main` both require a passing PR
- [ ] The stub handler exists, so T2 does not wait on the backend engineer

Item four matters more than it looks. **A pipeline nobody has seen fail is not known to
work.** Break it on purpose once, watch it go red, then fix it.

---

## Part 2 — what unblocks when admin access lands

In order, once the account has an admin IAM user:

1. **Bootstrap the state bucket by hand, with local state** — a pipeline cannot create the
   thing it needs in order to run. Versioning, encryption, public access blocked,
   `use_lockfile = true`, no DynamoDB table.
2. **Create the OIDC provider and deploy role.** One provider per issuer per account; the
   trust policy is scoped to `repo:crag0006/sportable:ref:refs/heads/dev`.
3. **Prove it with a throwaway workflow** that runs only `aws sts get-caller-identity`.
   Do not wire anything real until that prints the right account.
4. **`deploy-staging.yml`** — the eight steps on page 3 of `SportAble_Infra_Architecture.drawio`.

Then T1 (VPC → RDS → bastion), which is when the `terraform` job in this pipeline stops
skipping and starts earning its place.

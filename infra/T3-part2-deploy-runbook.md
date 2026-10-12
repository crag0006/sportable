# T3 Part 2 — Continuous Deployment Runbook

**SportAble Melbourne** · FIT5120 · Iteration 1 · Infra/Platform owner: Charan

| | |
|---|---|
| **Task** | T3 Part 2 — `deploy-staging.yml` (5.0 h) |
| **Serves** | Definition of Done — *"a push to `dev` reaches the CloudFront URL with no manual step"* |
| **Depends on** | T1 (VPC, RDS), T2 (CloudFront, API Gateway, Lambda), T3 Part 1 (CI, state bucket, branch protection) |
| **Written** | 30 Aug 2026 |
| **Status** | **Live.** First deploy 30 Aug (run `33303212942`); rollback rehearsed the same day (run `33304478786`) |

---

## The blocker that held this up, and how it was resolved

Part 1 shipped on 29 Aug. Part 2 could not start because the OIDC handshake
failed: every `sts:AssumeRoleWithWebIdentity` returned *"Not authorized."*

The account holder had scoped the deploy role's trust policy to:

```
repo:crag0006/sportable:*ref:refs/heads/dev*
```

A throwaway workflow (`oidc-smoke-test.yml`) decoded the token GitHub actually
mints and printed its `sub` claim:

```
repo:crag0006@186376784/sportable@1349074555:ref:refs/heads/dev
```

GitHub injects **immutable numeric IDs** for repositories created after
15 Jul 2026 — one after the owner, one after the repository name. The policy's
wildcard sat *after the colon*, where nothing is inserted, so the literal prefix
`repo:crag0006/sportable:` could never match. This was not a `StringLike` versus
`StringEquals` problem; the pattern itself was unmatchable.

Because the real IDs were now known, the fix used `StringEquals` — stricter than
any wildcard, and no guessing:

```json
"StringEquals": {
  "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
  "token.actions.githubusercontent.com:sub": [
    "repo:crag0006@186376784/sportable@1349074555:ref:refs/heads/dev",
    "repo:crag0006@186376784/sportable@1349074555:ref:refs/heads/main"
  ]
}
```

Applied by the account holder on 30 Aug. Verified the same morning:

```
sub:     repo:crag0006@186376784/sportable@1349074555:ref:refs/heads/dev
Arn:     arn:aws:sts::725699850301:assumed-role/sportable-github-deploy/GitHubActions
s3 ls:   sportable-tfstate-725699850301
```

> **The lesson worth keeping.** Do not guess the shape of a claim you have never
> seen. A ten-line workflow that decodes the token and prints one field turned a
> two-day guessing game into a five-minute fix. Write that probe *before* wiring
> the real pipeline, every time.

**`oidc-smoke-test.yml` is now redundant.** Leave it until the first real deploy
succeeds, then delete it — it is scaffolding, and scaffolding left up gets
mistaken for structure.

---

## The one idea this whole file rests on: version ≠ alias

Everything below follows from this, so it is worth being slow about.

A Lambda **version** is an immutable, numbered snapshot of code and
configuration. Version 3 is version 3 forever. It cannot be edited, only
superseded.

A Lambda **alias** is a movable pointer at one version. Ours is called `live`.

```
                    ┌────────────┐
                    │  version 3 │  ← last week's code, still there, untouched
                    └────────────┘
                          ▲
                          │  (rollback moves the pointer back here)
                          │
   API Gateway ──────► [ live ] ──────► ┌────────────┐
                                        │  version 4 │  ← serving traffic now
                                        └────────────┘
                                        ┌────────────┐
                                        │  version 5 │  ← just published,
                                        └────────────┘     nobody sees it yet
```

**API Gateway is wired to the alias ARN, never to the function ARN.** Check
`infra/modules/api/gateway.tf` — the integration URI is `module.api.alias_arn`.
That indirection is the entire reason a rollback is one API call.

Terraform's job stops at *publishing* version 5. It deliberately does not move
the pointer:

```hcl
resource "aws_lambda_alias" "live" {
  # ...
  lifecycle {
    ignore_changes = [function_version]
  }
}
```

Without `ignore_changes`, every `terraform apply` would drag the alias forward
with it, and there would be no gap in which to run migrations — nor any way for
the pipeline to roll back without a second Terraform run.

**Moving the alias is the release.** Everything before it is preparation;
everything after it is verification.

---

## Why the step order is the design

```
  1.  terraform apply       →  version 5 exists.  Traffic still on version 4.
  2.  migrations            →  the schema moves forward.
  3.  update-alias          →  live → 5.  This is the release.
  4.  frontend to S3        →  new assets uploaded.
  5.  CloudFront invalidate →  edges stop serving the old index.html.
  6.  smoke test            →  prove it from outside.
  7.  on failure: rollback  →  live → 4.
```

Put migrations *after* the alias shift and you get the classic outage: the
migration fails halfway, and new code is already serving against a schema that
never finished moving. In this order a failed migration stops the deploy while
**version 4 is still serving** — the site never goes down. It just does not move
forward, which is the correct outcome for a broken deploy.

The rollback target is captured in step 0, **before anything changes.** Reading
it afterwards would read the value you just wrote.

### What is deliberately *not* rolled back

| | Rolled back? | Why |
|---|---|---|
| Lambda alias | **Yes** | One call, seconds, no rebuild. The old version was never destroyed. |
| Frontend in S3 | No | The bucket is versioned; a bad asset is recoverable by hand. Automating it risks racing the invalidation. |
| Infrastructure | No | An automatic `terraform` reversal on failure is more dangerous than the failure. Read the plan and decide. |

---

## What was built

| File | Change |
|---|---|
| `.github/workflows/deploy-staging.yml` | **New.** The pipeline. |
| `infra/modules/api/outputs.tf` | **New output** `function_version` |
| `infra/envs/staging/outputs.tf` | **New output** `api_function_version` |

### Why the new output exists

The pipeline has to know *which* version to promote. Two ways to find out:

```bash
# Guess — ask Lambda for its highest-numbered version
aws lambda list-versions-by-function --function-name sportable-staging-api
```

```bash
# Know — ask Terraform what it just published
terraform output -raw api_function_version
```

The first is a race. If two deploys overlap, the highest version may belong to
the *other* run, and you promote code that was never tested by this one. The
second is exact. It costs six lines of HCL.

A local plan confirmed the change touches nothing real:

```
Changes to Outputs:
  + api_function_version = "4"

You can apply this plan to save these new output values to the Terraform
state, without changing any real infrastructure.
```

---

## Reading the workflow

### Triggers

```yaml
on:
  push:
    branches: [dev]
  workflow_dispatch:
```

`dev` is protected, so a push to `dev` is always a merged PR that already passed
CI. That is why this workflow does not re-run the tests — CI is the gate,
deployment is the consequence.

`workflow_dispatch` lets you re-deploy without an empty commit, which you will
want after changing an SSM parameter.

### Concurrency — note what differs from `ci.yml`

```yaml
concurrency:
  group: deploy-staging
  cancel-in-progress: false
```

`ci.yml` sets `cancel-in-progress: true`, because cancelling a lint run costs
nothing. Here it is **false**. A cancelled deploy can leave a half-applied
Terraform state, or a published version with the alias never moved. A queued
deploy is correct behaviour; a killed one is a mess to unpick.

### `terraform_wrapper: false`

`hashicorp/setup-terraform` installs a wrapper that decorates stdout so it can
post plans as PR comments. That decoration breaks `terraform output -raw`, which
five steps here depend on. Turning the wrapper off is not optional.

### plan → apply, not `apply -auto-approve`

```bash
terraform plan  -out=tfplan -detailed-exitcode
terraform apply tfplan
```

Applying a **saved plan** guarantees that what ran is exactly what was printed
in the log above it. `apply -auto-approve` silently re-plans, so the log and the
action can differ — which is precisely when you least want them to.

`-detailed-exitcode` returns `0` for no changes, `2` for changes, `1` for an
error. Without it, a genuine failure and a clean no-op both exit `0`.

### The smoke test checks three things, through CloudFront

Not through the API Gateway URL. The CloudFront URL is what a user types, and it
is the only address that exercises the whole chain: TLS, the cache behaviours,
the origin, the alias, the function.

| Check | Guards against |
|---|---|
| `GET /api/v1/health` → `200`, body `"status": "ok"` | The API is reachable and the alias points at working code |
| `GET /api/v1/venues/<nonexistent>` → `content-type: application/json` | **Regression guard.** A distribution-wide `custom_error_response` once turned every API 404 into a `200` of HTML. The frontend cannot parse that. |
| `GET /` → `200` | The SPA is served |

That second check earns its place: the bug it guards passed `terraform apply`,
`validate`, `tflint` and `checkov`. Only a `curl` found it.

---

## The migration gap — read this before Backend commits a revision

`backend/migrations/versions/` is **empty today**. Backend #2 owes the first
Alembic revision around day 9.

**A GitHub runner cannot reach our database.** RDS has no public IP, and the
account has no NAT Gateway — that is ADR-002's saving, and it is working as
intended. There is no network path from a runner to `sportable-staging-db`.

So the migration step is **fail-closed**:

```bash
COUNT=$(find backend/migrations/versions -name '*.py' ! -name '__*' | wc -l)
if [ "$COUNT" -eq 0 ]; then
  echo "No Alembic revisions exist yet — nothing to migrate."
  exit 0
fi
echo "::error::... Deploy stopped BEFORE the alias moved ..."
exit 1
```

While there are no revisions, the deploy proceeds. **The day the first revision
lands, the deploy stops** — before the alias moves, so staging keeps serving the
previous release. That is loud, and it is meant to be. Silently skipping
migrations would ship a handler against a schema that was never migrated.

### The fix, when that day comes

Build a **migration Lambda** inside the VPC:

- Same private subnet and security group as the API Lambda, so it can reach RDS
- Zip carries `alembic`, `sqlalchemy`, `psycopg` and `backend/migrations/`
- Handler runs `alembic upgrade head` and returns the result
- The pipeline replaces the fail-closed step with a synchronous
  `aws lambda invoke`, and fails the deploy on a non-zero result

Two alternatives were considered and rejected:

| Option | Why not |
|---|---|
| **NAT Gateway** so the runner can reach RDS | USD $43.07/month, and it spends ADR-002's entire saving to solve a problem a $0 Lambda solves |
| **SSH tunnel through the bastion** | Requires a long-lived private key in repository secrets. The Definition of Done says *no credential exists in the repo or in GitHub secrets*. Also, the bastion is normally stopped and its security group admits one home IP. |

> Note the shape of both rejections: the cheap answer and the secretless answer
> are the same answer. That is usually a sign it is the right one.

---

## First deploy — do it in this order

### 1. Commit and open the PR

The three `*-runbook.md` files in `infra/` stay untracked by convention.

```bash
cd "/Users/charankumarraghupatruni/Monash/Studio Project/sportable/sportable-git"

git add .github/workflows/deploy-staging.yml \
        infra/modules/api/outputs.tf \
        infra/envs/staging/outputs.tf

git commit -m "ci: deploy dev to staging automatically

Publishes via Terraform, migrates, then shifts the Lambda alias — in that
order, so a failed migration never leaves new code against an old schema.
Smoke-tests through CloudFront and rolls the alias back if it fails.

Adds api_function_version so the pipeline promotes the version this run
published rather than the highest-numbered one, which races under
concurrent deploys."

git push -u origin feature/infra-frontend
gh pr create --base dev --fill
```

CI must go green — all four checks — before `dev` will accept the merge.

### 2. Merge, and watch the first deploy

```bash
gh run watch --exit-status
```

Expect roughly 4–6 minutes, most of it the CloudFront invalidation.

### 3. Verify by hand, not only by the green tick

```bash
export AWS_PROFILE=sportable

aws lambda get-alias --function-name sportable-staging-api --name live \
  --query FunctionVersion --output text

curl -s https://d1nsbukoi7bexf.cloudfront.net/api/v1/health
curl -s -o /dev/null -w '%{http_code}\n' https://d1nsbukoi7bexf.cloudfront.net/
```

### 4. Rehearse a rollback *on purpose*

A rollback path you have never exercised is a hope, not a control. T6 asks for
this explicitly. The cheapest rehearsal:

```bash
# Move the alias back one version by hand.
aws lambda update-alias --function-name sportable-staging-api \
  --name live --function-version 3 --query FunctionVersion --output text

# Confirm the site still answers on the old code.
curl -s https://d1nsbukoi7bexf.cloudfront.net/api/v1/health

# Re-run the pipeline; it should carry you forward again.
gh workflow run deploy-staging.yml --ref dev
```

To exercise the *automatic* path, break the smoke test deliberately — point it
at a route that does not exist, push, and watch the alias return itself. Undo
the change afterwards.

---

## Current state, for reference

| | |
|---|---|
| Site | `https://d1nsbukoi7bexf.cloudfront.net` |
| Bucket | `sportable-staging-site-725699850301` |
| Distribution | `E1GR3UG46RQPL8` |
| Function | `sportable-staging-api` |
| Versions published | `3`, `4` |
| `live` points at | `4` |
| RDS | `sportable-staging-db` — **stopped** |
| Bastion | `i-0960d1df1b615b7bd` — **stopped** |

Both compute resources are stopped and month-to-date spend is effectively zero.
The pipeline does not need either of them running: the stub handler serves
fixtures and never opens a database connection.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` does not match | Run `oidc-smoke-test.yml`, read the printed `sub`, pin the policy to it exactly |
| `Error acquiring the state lock` | A previous run was cancelled mid-apply | Check no run is in flight, then `terraform force-unlock <ID>`. Never force-unlock a *running* apply |
| `terraform output -raw` prints decoration | `terraform_wrapper` left on | It is set to `false` — check it was not removed |
| Deploy fails at *Database migrations* | Backend committed the first Alembic revision | Expected and correct. Build the migration Lambda — see above |
| Smoke test: API 404 has `content-type: text/html` | SPA fallback leaking into `/api/*` | Check the CloudFront Function is attached to the SPA behaviour **only**, not the distribution |
| `npm ci` fails: no lockfile | `frontend/package.json` exists without `package-lock.json` | Commit the lockfile. `npm ci` requires one by design |
| Site serves old assets after a deploy | Invalidation did not complete | The workflow waits for it. If skipped, check `index.html` was uploaded with `no-cache` |
| `AccessDenied` on `lambda:UpdateAlias` / `cloudfront:CreateInvalidation` | Deploy role lacks the action | We cannot read the role's policy (`iam:ListAttachedRolePolicies` is denied). Send the exact action and resource from the error to the account holder |

> **On that last row.** The smoke test proved the role can *assume* and *read*.
> It did not prove every write this pipeline performs. The first real run is
> also the first full permissions test — if it fails, the error names the exact
> missing action, which is all the account holder needs.

---

## Definition of done

- [x] OIDC assume-role verified from `dev`
- [x] Deploy workflow written, YAML validated, 18 steps
- [x] Terraform change plans clean — outputs only, no infrastructure churn
- [x] Version/alias split preserved; alias moved by the pipeline, not Terraform
- [x] Rollback captured before the shift, triggered only after it
- [x] Smoke test exercises the CloudFront URL, including the API-404 regression guard
- [x] Merged to `dev` and observed deploying end to end — run `33303212942`, 30 Aug
- [x] Rollback rehearsed deliberately — run `33304478786`, 30 Aug (see below)
- [ ] `oidc-smoke-test.yml` deleted once the first real deploy succeeds

**T3 is complete when you push a commit to `dev`, walk away, and the change is
live at the CloudFront URL with no further action.**

---

## Rollback rehearsal — 30 Aug 2026

Two drills. Both passed.

### Manual path

```
live -> 5   →  update-alias to 4  →  {"status": "ok"}  HTTP 200
            →  update-alias to 5  →  {"status": "ok"}
```

Roughly three seconds each way, no rebuild, no Terraform run.

### Automatic path — run `33304478786`

Method: **break the test, not the product.** A comment appended to `stub.py`
forced a new version; the smoke test's health check was pointed at a path that
404s. The deployed code was therefore correct throughout — if the rollback
mechanism itself had failed, staging would still have been serving something
that worked. A rehearsal should not be able to cause the outage it rehearses.

```
Currently live: 5
Published version: 6
Promote the new version              ✓   alias 5 → 6
attempt 1..5: HTTP 404 — retrying    ✗
##[error]health check returned HTTP 404
Roll back to the previous version    ✓   ::warning:: rolling back to version 5
```

Verified afterwards from outside CI:

| | |
|---|---|
| Versions | `3 4 5 6` — version 6 intact, simply not pointed at |
| `live` | `5` |
| `GET /api/v1/health` | `{"status": "ok", "service": "sportable-api"}` |
| `GET /` | HTTP 200 |

**The job ended red, which is the pass condition for this drill.** Total
exposure was ~35 seconds, nearly all of it the deliberate 5 x 5s retry loop —
and no user would have seen it, because version 5 served continuously. The
alias only pointed at 6 while the failing test ran.

Reverted immediately afterwards.

---

## Still open after this

| Item | Owner | Blocks |
|---|---|---|
| Migration Lambda | Infra, once Backend lands the first revision | Schema changes reaching staging |
| Budget alarm at USD $5 | Account holder — `budgets:ModifyBudget` is explicitly denied to us | T5. `aws ce get-cost-and-usage` is the manual substitute |
| ADR-001, 002, 003 | Infra | T6. ADR-003 is overdue and Frontend is waiting on it |
| CloudWatch alarms + SNS | Infra | T5 |
| Ingestion shell | Infra, handlers by Data | T4 |

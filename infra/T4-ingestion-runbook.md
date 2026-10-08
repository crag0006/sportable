# T4 — Scheduled Ingestion Runbook

**SportAble Melbourne** · FIT5120 · Iteration 1 · Infra/Platform owner: Charan

| | |
|---|---|
| **Task** | T4 — *Get open data into the database on a schedule* (6.0 h) |
| **Serves** | US1.3 — *"each result shows its access facts"* · AC1.3.1–1.3.3 and Epic 1's DoD |
| **Depends on** | T1 (VPC, RDS, S3 gateway endpoint), T3 (the pipeline), T5 (the alerts topic) |
| **Written** | 30 Aug 2026 |
| **Status** | Built and verified locally. Not yet applied. |

---

## Why this one matters more than it looks

> **Without this the database is empty and every search returns nothing.**

Everything built so far is plumbing. A marker who types into the search box
today gets zero results, and no amount of infrastructure quality compensates for
that. This is the task that turns a working system into a working product.

**The division of labour:** you build the shell, the Data team writes the
handlers. The contract between you is the S3 key convention and the handler
signature, both recorded in `data/README.md`.

---

## The one design decision everything follows from

Two Lambda functions, not one. The difference between them is a single
Terraform block:

```
                 vpc_config?   internet   RDS    S3
  fetch             no            yes      no    public endpoint
  load              yes           no       yes   gateway endpoint
```

A Lambda with **no** `vpc_config` runs on AWS-managed networking and can reach
the internet. Attach it to our private subnet and it inherits a route table with
no default route — it would hang trying to reach `data.vic.gov.au`, exactly as
the API handler hung trying to reach Parameter Store this morning.

A Lambda **with** `vpc_config` can reach RDS, and gets to S3 free through the
gateway endpoint that already exists.

One function cannot be both. The alternative — one function plus a NAT Gateway
at **USD $43.07/month** — buys nothing that splitting in two does not.

> This is the third time the same constraint has shaped a design decision:
> migrations (T3), the config read (T5), and now ingestion. It is worth
> internalising as a rule: **in this account, nothing inside the VPC can reach
> anything outside it.** Ask "which side does this need to be on?" before
> writing the function, not after it times out.

---

## What gets created

```
S3
  sportable-staging-raw-725699850301          versioned, AES256, no public access
    <dataset>/dt=YYYY-MM-DD/<filename>        what the publisher sent, unmodified
    _manifests/<key>.json                     what we observed about it
  sportable-staging-quarantine-725699850301   rejected rows, kept as evidence

Lambda
  sportable-staging-fetch    256 MB   60 s   outside the VPC
  sportable-staging-load     512 MB  120 s   inside the VPC, az-a

EventBridge
  fetch-vic_sport_rec         cron(0 16 ? * SUN *)   DISABLED
  fetch-public_toilets_nptm   cron(0 17 ? * SUN *)   DISABLED
  fetch-ptv_gtfs              cron(0 18 ? * SUN *)   DISABLED
  fetch-osm                   cron(0 19 1 * ? *)     DISABLED

CloudWatch
  fetch-failures   >= 3 errors in a day
  load-failures    >= 1 error in 5 min
```

`Plan: 29 to add, 1 to change, 0 to destroy.`

---

## Decisions worth understanding

### The raw zone keeps bytes, not records

`fetch` does not parse, validate, reshape or filter. What arrived is what is
written.

That is the whole value of a raw zone: when a transform turns out to be wrong in
three weeks — and one will — the fix is a re-run over data we already hold.

It matters here more than usual because **these publishers overwrite.**
Victoria's open data portal serves one current file per dataset. There is no
archive to ask for last month's version. If we did not keep it, it is gone.

### Why the schedules are created DISABLED

No source has a URL yet — those belong to the Data team. A rule with no URL
behind it is created but not armed, so:

- the shell is **visible in the console**, and the Data team can see exactly what
  is waiting for them
- it **cannot fire** against a source nobody has configured

Supply a URL in `infra/envs/staging/main.tf` and the rule arms itself on the
next deploy. No Terraform structure changes.

### Why a fetch failure needs three strikes and a load failure needs one

| | Threshold | Reasoning |
|---|---|---|
| `fetch-failures` | 3 per **day** | EventBridge already retries three times over an hour. Alarming on the first attempt would page us for something the retry policy is about to fix. Three in a day means the retries did not help. |
| `load-failures` | 1 per **5 min** | A file landed and was not processed. Nothing retries this, and a silently unprocessed file is exactly how the database stays empty while every dashboard looks fine. |

Both use `treat_missing_data = "notBreaching"`. Silence is the normal state for a
weekly job; without it the fetch alarm would sit in `INSUFFICIENT_DATA` six days
out of seven.

### Why the S3 notification filters on dataset prefixes

`load` writes its manifests back into the bucket it is watching. A bucket-wide
notification would invoke it again for every manifest — the handler's
`_manifests/` guard stops the recursion, but only after paying for a cold start
to discover there is nothing to do.

S3 notification filters can only **include** a prefix, never exclude one. So the
configuration names the four prefixes we want. The handler keeps its guard
anyway: two mechanisms against a runaway loop is the right number when one of
them is a config someone might widen later without thinking.

### Times are staggered on purpose

16:00, 17:00, 18:00 UTC Sunday, and 19:00 on the first of the month. That is
early Monday in Melbourne, after these publishers have finished their own weekly
updates.

The hour gaps are not cosmetic: **this account's total Lambda concurrency is 10**
and the Free plan will not raise it. Four simultaneous multi-megabyte fetches,
plus whatever the API is doing, is a self-inflicted throttle.

---

## What is deliberately NOT built

**The database write.**

`load` reads the object, checks it parses, and writes a manifest carrying:

```json
"rows_loaded": 0,
"load_status": "pending_loader"
```

Two reasons, and only the second is an infrastructure problem:

1. The transforms and column contracts belong to the Data team. There is nothing
   yet to call.
2. **`psycopg` is not in the deployment package**, and this project has no build
   step that installs dependencies into a Lambda zip. `archive_file` zips a
   directory; it cannot run pip.

That second reason is **the same gap that blocks the Alembic migration Lambda**
described in the T3 runbook. One build step solves both, and it should be built
once rather than twice.

The marker in the manifest is deliberate. A green invocation must not be able to
imply that data reached Postgres.

### The build step, when someone takes it on

```bash
uv pip install --target build/ --python-platform x86_64-manylinux2014 \
  "psycopg[binary]" alembic sqlalchemy
cp -r data/ingestion build/
```

Then either a `null_resource` with `local-exec` before `archive_file`, or a CI
step that produces the zip. Both my laptop and the runner have `uv`.
`--python-platform` matters: the deployed functions are `x86_64`, and installing
on a Mac without it produces arm64 wheels that fail at import with a message
that does not mention architecture.

---

## Applying and testing

Let the pipeline apply it. A push to `dev` does the whole thing.

### The smoke test — proves the path without needing a publisher

This is the important one. It exercises **fetch reaching the internet → writing
to S3 → the notification firing → load reading it back from inside the VPC
through the gateway endpoint.** Four separate things that can each be wrong.

```bash
export AWS_PROFILE=sportable

aws lambda invoke --function-name sportable-staging-fetch \
  --payload '{"dataset":"vic_sport_rec","url":"https://checkip.amazonaws.com/"}' \
  --cli-binary-format raw-in-base64-out /dev/stdout
```

`checkip.amazonaws.com` returns a few bytes and is always up. It is not a real
source — the point is to prove the plumbing, not the data.

Expect a response naming the key it wrote. Then, a few seconds later:

```bash
RAW=$(cd infra/envs/staging && terraform output -raw raw_bucket)
aws s3 ls "s3://$RAW/vic_sport_rec/" --recursive
aws s3 ls "s3://$RAW/_manifests/" --recursive
```

A manifest under `_manifests/` means the load function ran. Read it:

```bash
aws s3 cp "s3://$RAW/_manifests/vic_sport_rec/dt=$(date -u +%F)/.json" - 2>/dev/null \
  || aws s3 ls "s3://$RAW/_manifests/" --recursive
```

### If the fetch invocation fails

The most likely cause is the execution role. `sportable-lambda-pipeline` was
pre-built by the account holder and **we cannot read its policies** — the same
constraint as the API's role. It needs at least:

```
s3:PutObject, s3:GetObject   on the raw and quarantine buckets
AWSLambdaVPCAccessExecutionRole   (for the load function's ENI)
```

The error names the exact action. Send that to the account holder.

---

## The manual fallback — and when to take it

The plan is explicit that ingestion may slip, and that the fallback is legitimate:

> The Data team loads the first dataset by hand over T1's bastion and automated
> ingestion moves to Iteration 2. **If you take it, write it down the day you
> decide** — an undocumented deferral is indistinguishable from a failure.

This shell makes the fallback cheaper rather than redundant. Because `load` is
triggered by **an object landing**, not by a schedule, a file uploaded by hand is
processed exactly like a scheduled one:

```bash
aws s3 cp ./toilets.geojson \
  "s3://$RAW/public_toilets_nptm/dt=$(date -u +%F)/toilets.geojson"
```

Nothing special-cases it. The manifest appears, and when the loader exists the
same file loads without being re-fetched.

**Decision point: if no source URL is configured by Wed 3 Sep**, take the
fallback, and record it here with the date.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Fetch invocation times out at 60 s | Publisher is slow or unreachable | The handler's own 20 s HTTP timeout should fire first and name the URL. If it does not, the URL is wrong |
| `no URL configured for dataset 'x'` | Expected until the Data team supplies endpoints | Set it under `module.ingestion.sources`. The rule arms on the next deploy |
| Fetch succeeds, no manifest appears | Notification not firing | The filter is per dataset prefix. A key that does not start with a configured dataset name is not watched |
| `AccessDenied` on PutObject | Execution role lacks S3 permissions | We cannot read that role. Send the exact action from the error to the account holder |
| Load times out | It is in the VPC and reached for something outside it | Nothing inside the VPC can reach the internet or SSM. Pass the value in as an environment variable |
| Manifests trigger more manifests | Notification widened to the whole bucket | Filters must stay per dataset prefix. The handler's `_manifests/` guard is the second line, not the first |
| Rules fire but nothing happens | Rule is `DISABLED` | It is disabled precisely because its URL is empty. That is the design |
| Local `terraform plan` shows an unexpected `api` change | Zip built on macOS differs from the runner's | Harmless. CI builds on Ubuntu consistently; the change will not appear there |

---

## Verified locally

```
terraform fmt -check -recursive   clean
terraform validate                Success
tflint --recursive                exit 0
checkov -d infra                  173 passed, 0 failed, 77 skipped
ruff / ruff format / mypy (data)  clean
pytest (data)                     9 passed, 91% coverage
terraform plan                    29 to add, 1 to change, 0 to destroy
```

Two latent CI breaks were found and fixed on the way. Both were hidden by the
`Data` job's guard, which skipped every step while `data/` held no Python:

- **`ruff` was not a dev dependency of `data/`.** CI runs `uv run ruff check .`
  there, which would have failed to spawn the moment the guard flipped.
- **`mypy ingestion derive` fails outright on a directory with no Python at
  all.** `derive/` now has an `__init__.py`, which it needed anyway.

---

## Definition of done

- [x] S3 raw zone — versioned, encrypted, public access blocked, Glacier IR at 90 days, old versions expiring at 180
- [x] Quarantine bucket, deliberately without a lifecycle rule
- [x] Four EventBridge schedules matching each publisher's cadence, staggered, created DISABLED
- [x] Fetch Lambda outside the VPC, with a bounded HTTP timeout
- [x] Load Lambda inside the VPC, triggered by S3, reaching S3 through the gateway endpoint
- [x] Two alarms publishing to T5's topic
- [x] Handler tests pinning the key convention and the manifest shape
- [x] `data/README.md` updated with the real contract
- [ ] Applied via the pipeline
- [ ] Smoke test run end to end
- [ ] Source URLs supplied by the Data team
- [ ] Loader writing rows — **blocked on the psycopg build step**

---

## What this leaves open

| Item | Owner | Blocks |
|---|---|---|
| Lambda dependency build step | Infra | The loader AND the migration Lambda. One step, two problems |
| Source URLs and licences | Data team | Arming the schedules |
| Transforms, validators, loaders | Data team | Rows in the database |
| SNS subscription confirmation | Charan — deliberately deferred | Alarm email, including these two |

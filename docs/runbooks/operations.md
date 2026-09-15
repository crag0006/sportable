# Operations Runbook — SportAble staging

**Organised by what has gone wrong, not by which service it is.** At 2am nobody
wants a tour of the architecture; they want the four commands that fix it.

For *how the system was built and why*, read `infra/*-runbook.md` and
`docs/adr/`. This file is only for operating it.

---

## Before anything

```bash
export AWS_PROFILE=sportable          # 725699850301. Nothing here works without it.
cd infra/envs/staging                 # every `terraform output` below assumes this
```

If a command returns `AccessDenied`, check the profile first. There are three
AWS accounts in play and `aws configure` remembers whichever was used last.

## The system in ten lines

| | |
|---|---|
| Site | `https://d1nsbukoi7bexf.cloudfront.net` |
| API | same origin, under `/api/v1/` |
| Lambda | `sportable-staging-api`, alias `live` |
| Database | `sportable-staging-db` — **normally stopped** |
| Bastion | the only way in to the database — **normally stopped** |
| Site bucket | `sportable-staging-site-725699850301` |
| Distribution | `E1GR3UG46RQPL8` |
| Region | `ap-southeast-2` |
| Deploys | merge to `dev`. Nothing is deployed by hand |
| Alarms | six, all publishing to `sportable-staging-alerts` |

---

# The site is down

**First, confirm it — from outside, not from your editor.**

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://d1nsbukoi7bexf.cloudfront.net/
curl -s https://d1nsbukoi7bexf.cloudfront.net/api/v1/health
```

| What you see | What it means | Go to |
|---|---|---|
| Site 200, API fails | The API alias points at bad code | **Roll back the API**, below |
| Site 403 or blank, API fine | The frontend upload went wrong | **The frontend is broken**, below |
| Both fail | CloudFront or the distribution config | Check the last deploy first |

## Roll back the API — about one second

This is the fix for *"the last deploy broke the API"*. It does not need
Terraform, a rebuild, or the pipeline.

```bash
# 1. What is serving now, and what can I go back to?
aws lambda get-alias --function-name sportable-staging-api --name live \
  --query FunctionVersion --output text
aws lambda list-versions-by-function --function-name sportable-staging-api \
  --query 'Versions[?Version!=`$LATEST`].Version' --output text

# 2. Point traffic at the previous version.
aws lambda update-alias --function-name sportable-staging-api \
  --name live --function-version <PREVIOUS> --query FunctionVersion --output text

# 3. Confirm.
curl -s https://d1nsbukoi7bexf.cloudfront.net/api/v1/health
```

Versions are immutable and are never deleted, so the old code is always still
there. You are moving a pointer, not restoring a backup.

**Then tell people the alias is pinned.** The next merge to `dev` will move it
forward again and reintroduce whatever you just backed out. Fix the cause, or
the rollback lasts until the next deploy.

## The frontend is broken

The bucket holds the built site. Check what is actually in it:

```bash
aws s3 ls s3://sportable-staging-site-725699850301/ --recursive
```

Expect `index.html`, `assets/…js`, `assets/…css`. If `index.html` is missing or
is the 458-byte placeholder, the upload step failed.

**Re-run the deploy rather than uploading by hand** — a hand upload will be
overwritten by the next deploy and hides the real failure:

```bash
gh workflow run deploy-staging.yml --ref dev
gh run watch
```

Versioning is on, so a previous `index.html` is recoverable:

```bash
aws s3api list-object-versions --bucket sportable-staging-site-725699850301 \
  --prefix index.html --query 'Versions[].[VersionId,LastModified,IsLatest]' --output table
```

---

# A deploy failed

**Look at which step failed before doing anything.** The pipeline may already
have cleaned up after itself.

```bash
gh run list --workflow=deploy-staging.yml --limit 5
gh run view <id> --log-failed
```

| Failed at | The pipeline already… | You must |
|---|---|---|
| terraform plan / apply | changed nothing, or applied partially | Read the log. Re-run once; if it fails the same way, fix the code |
| Database migrations | stopped **before** the alias moved | Nothing is broken. See *Migrations*, below |
| Promote the new version | not shifted traffic | Old version still serving. Check `lambda:UpdateAlias` permission |
| Anything after Promote | **rolled the alias back automatically** | Confirm with `get-alias`; the site is on the previous version |

The rollback step only runs if the alias had already moved. A failure before
that point never changed what users see.

**If a run was cancelled mid-apply**, the state lock may be held:

```bash
# Only after confirming no run is in flight. NEVER force-unlock a running apply.
terraform force-unlock <LOCK_ID>
```

---

# An alarm fired

Six alarms, all publishing to `sportable-staging-alerts`.

```bash
aws cloudwatch describe-alarms \
  --query 'MetricAlarms[?StateValue!=`OK`].[AlarmName,StateReason]' --output text
```

No output means nothing is in alarm.

| Alarm | What it actually means | First thing to check |
|---|---|---|
| `lambda-errors` | The API threw an unhandled exception | `aws logs tail /aws/lambda/sportable-staging-api --since 30m` |
| `lambda-throttles` | Requests rejected before running. **This account's total concurrency is 10 and the Free plan will not raise it** | Is something else in the account also running? |
| `lambda-duration` | Average approaching the 10 s timeout | Almost always a database connection hanging rather than failing fast |
| `api-5xx` | Gateway returned server errors | `aws logs tail /aws/apigateway/sportable-staging-api --since 30m` and look for `integrationErrorMessage` |
| `rds-connections` | Above 40; the instance allows ~112 | A handler not releasing connections. Connection pooling is on Backend's list |
| `rds-free-storage` | Under 2 GB of 20 GB. **Autoscaling is off by design, so this will not fix itself** | What grew? Ingestion, or log tables |

> **The subscription is not confirmed.** As of 1 Sep 2026 the email
> subscription is `PendingConfirmation`, which was a deliberate decision — so
> **alarms change state but nobody is emailed.** Until that changes, the
> `describe-alarms` command above is the only way you will find out. To turn it
> on, click the link in the AWS confirmation email and check:
> ```bash
> aws sns list-subscriptions --query 'Subscriptions[].[Endpoint,SubscriptionArn]' --output table
> ```
> A `SubscriptionArn` of literally `PendingConfirmation` means that address is deaf.

**The ingestion pipeline has its own alarms**, one `Errors` alarm per function —
`sportable-staging-fetch-errors`, `-load-errors`, `-status-builder-errors`. The
`describe-alarms` command above lists them too. For what they mean when the
source is DS-09, see the next section.

---

# The events data is stale, wrong or missing (DS-09 / AAA Play)

DS-01 to DS-08 are file downloads from government portals with pinned hashes.
**DS-09 is someone else's live WordPress site** — Reclink's, behind Wordfence,
with no contract with us and no obligation to keep its shape. It is by far the
most likely source in the register to fail on any given week, which is why it
has its own EventBridge rule rather than sharing one.

| | |
|---|---|
| Fetch function | `sportable-staging-fetch` |
| Schedule | `cron(30 16 ? * SUN *)` — weekly, Sunday 16:30 UTC, in its own slot |
| Raw object | `s3://sportable-staging-raw-725699850301/aaaplay/dt=YYYY-MM-DD/aaaplay.json` |
| Size of a real pull | 15.4 MB, from **18** HTTP requests, in **28.06 s** |
| Timeout | `fetch_timeout_seconds` is 900 s, so the pull uses about 3% of the budget |

**One object, not eighteen files.** The load function is triggered per S3 object
and opens one transaction per object, so the whole pull lands as a single body
with a single SHA-256. That is what makes change detection, the manifest and the
force flag below work on DS-09 exactly as they do on a file source.

## Force a DS-09 reload by hand

The fetch handler skips a source whose payload hashes identical to last week's.
`force` is what overrides that.

```bash
aws lambda invoke \
  --function-name sportable-staging-fetch \
  --cli-binary-format raw-in-base64-out \
  --payload '{"source_ids": ["DS-09"], "force": true}' \
  /tmp/ds09.json

cat /tmp/ds09.json
```

The handler accepts three shapes, and they are documented at the top of
`data/ingestion/extractors/handler.py`:

```
{"source_id": "DS-01"}
{"source_ids": ["DS-01", "DS-02"]}
{"source_ids": ["DS-01"], "force": true}
```

An event carrying neither `source_id` nor `source_ids` raises. `force` is read
once for the whole invocation, so it applies to every id in the list — invoke
DS-09 on its own rather than forcing four sources you did not mean to.

**What the outcomes mean:**

| `outcome` | Meaning |
|---|---|
| `landed` | A new object was written. Loading follows automatically from the S3 notification |
| `no_change`, reason `identical_payload_hash` | The register has not moved. **Nothing was written, and that is correct** |
| `skipped` | The card's `tier` is not in `FETCHABLE_TIERS` (`reference`, `transit`, `static`). DS-09 is `tier: reference` — if it ever reads `skipped`, someone changed the card |

Landing an object is only half of it. **Confirm the load ran**, because the
fetch succeeding tells you nothing about the transaction:

```bash
aws logs tail /aws/lambda/sportable-staging-fetch --since 15m --format short
aws logs tail /aws/lambda/sportable-staging-load  --since 15m --format short
```

Every notable step writes one structured JSON line with an `event` field —
`FETCH_LANDED`, `FETCH_SKIPPED`, `FETCH_FAILED`, `FETCH_RUN_SUMMARY`,
`HASH_PIN_MISMATCH`. Grep on that field, not on prose.

## A load aborted, or the rejection rate is climbing

**`sportable-staging-load-aborted`** — a load crossed its rejection threshold
and stopped. Thresholds are **15% by default and 30% for DS-01**, and they live
in `data/ingestion/loaders/loader.py` next to the reasoning for each.

**Look in the quarantine BUCKET, not the quarantine table.** `write_quarantine()`
inserts inside the load transaction and an abort rolls that transaction back, so
on this path the table is empty. The rows are written to S3 first, precisely so
they survive:

```
aws s3 ls s3://sportable-staging-quarantine-<account>/ --recursive | tail
```

Then work out which of the two things happened:

| | What it means | What to do |
|---|---|---|
| The publisher changed | A column vanished, a type changed, a code list grew | Re-profile the source card and update the transformer |
| The transform is wrong | A rule that was right last week is wrong on this payload | Fix the transformer, re-run against the same raw object |

**Do not raise the threshold to make the load pass.** The number came from the
source card's documented coverage — DS-01's 30% is cited to the 14 of 52 in-area
venues that publish no coordinates. Raising it to get a green run discards the
only guard that distinguishes a bad publish from a normal one.

**`sportable-staging-ds09-quarantine-rate-approaching`** — a DS-09 load
*committed*, but rejected more than 10% of its rows. Nothing failed. This is the
early warning: compare the rate against the DS-09 source card before touching
anything, and if the new rate is the publisher's new normal, re-profile the card
and say so there rather than adjusting the alarm.

Scoped to DS-09 deliberately. DS-01 quarantines a documented 26.92%, so a
register-wide version of this alarm would sit red forever. A second automated
source needs its own baseline from a real run.

## The DS-09 alarms, and what to do when one fires

> **Read this first: I7 landed on 15 Sep, with one documented gap.** Two DS-09
> alarms now exist alongside the per-function `Errors` alarm:
> `sportable-staging-ds09-fetch-failed` (filters `FETCH_FAILED` for DS-09) and
> `sportable-staging-ds09-data-stale` (filters `LOAD_ABORTED` for DS-09 — fresh
> JSON landed, the transaction rolled back, the database still serves last
> week's programmes).
>
> **What is still NOT built** is the literal "no successful DS-09 load in 14
> days" alarm. That is a CloudWatch limit rather than an oversight: an alarm's
> total evaluation range is capped at one day
> (`EvaluationPeriods x Period <= 86,400 s`), and 24 hours of silence from a
> weekly pipeline is normal six days out of seven, so forcing it with
> `treat_missing_data = "breaching"` would page Monday through Saturday. Doing
> it properly needs a scheduled function publishing an "hours since last
> successful load" gauge, which needs a new execution role — and this account's
> principals hold PowerUserAccess with no IAM. The 14-day threshold is enforced
> in the product layer instead, through SSM and `possibly_out_of_date`.
>
> **The consequence to know:** if the DS-09 EventBridge rule is manually
> disabled, staleness is permanent and silent. Re-enabling a disabled rule is a
> checklist item below, not something an alarm will remind you of.

**Fetch failure — `sportable-staging-fetch-errors`.**
The handler raises at the end of a run if any source in the payload failed, so
this alarm means *"at least one source did not land"* and not *"DS-09 is
broken"*. DS-09 runs alone in its own rule precisely so this is unambiguous when
it fires at 16:30 on a Sunday.

```bash
aws logs filter-log-events --log-group-name /aws/lambda/sportable-staging-fetch \
  --filter-pattern '{ $.event = "FETCH_FAILED" }' --start-time $(( ($(date +%s) - 86400) * 1000 )) \
  --query 'events[].message' --output text
```

| What the log says | What it means | Do this |
|---|---|---|
| HTTP 429 | Quota reached. `NO_RETRY_STATUS` includes 429, so it did **not** retry, by design | Wait. Do not re-invoke. Eighteen requests a week should stay invisible to a charity's WordPress site, and hammering it is how that stops being true |
| HTTP 403, or a Wordfence interstitial | The site's WAF has taken exception to us | Do not retry from a loop. Check the User-Agent is still `SportAbleMelbourne-Fetch/1.0` and raise it with the team before anything automated runs again |
| Timeout, or a 5xx | Publisher outage | Nothing to do. The next scheduled run picks it up. Stale events are the risk, not a failed fetch |
| `... exceeded MAX_PAGES` | Pagination is looping, or the register genuinely grew past six pages | The collector refuses to keep requesting rather than hammering the site. Look at `X-WP-TotalPages` by hand before raising the cap |
| `... returned no records` | A collection came back empty | **Deliberately fatal.** An empty collection is not a quiet week — writing it would replace the register with nothing. Nothing was written. Investigate upstream |
| `KeyError`, or a shape error from `aaaplay.py` | The API changed under us | See **AAA Play changed its ACF fields**, below |

**One failed week is not an incident.** The data was already a week old and the
previous load is still serving. Two consecutive weeks is, because nothing on the
site tells a user the events are stale.

**Freshness — no successful DS-09 `load_run` within the staleness window.**
This is the alarm that matters more than the fetch one, and it is the one that
does not exist yet. The reason it matters: **stale events are worse than absent
ones.** A user travels to a programme that ended. A fetch failure is loud; a
source that quietly keeps returning last month's body is not, and the `no_change`
path is indistinguishable from a healthy quiet week until you look at dates.

Until the alarm exists, check it by hand when you are in the database anyway:

```sql
SELECT source_id, MAX(started_at) AS last_run, MAX(finished_at) AS last_finish
  FROM load_run WHERE source_id = 'DS-09' GROUP BY source_id;
```

`source.stale_after_days` is the column that would drive this, and the value
recorded for DS-09 — 180 — **is a guess made before the first real load**, not a
figure read off one. It should be cited from a real run, the way DS-01's
quarantine threshold of 30% is, before anyone treats a freshness alarm as
authoritative.

**Quarantine rate.** The mechanism is `MAX_QUARANTINE_RATE_BY_SOURCE` in
`data/ingestion/loaders/loader.py`, and the load aborts rather than writing a
partial dataset. **DS-09 has no entry, so it falls back to the default.** A
DS-09 abort is not a signal to raise the number until the load passes — that is
stated in the file and it is the rule. If DS-09 exceeds its threshold, the
publisher's coverage changed and the card needs re-profiling.

## AAA Play changed its ACF fields

**The ACF field set is not a contract.** Nobody at Reclink owes us a stable
schema, there is no versioning on the endpoints, and a WordPress plugin update
can add, remove or retype a field on any Tuesday. Treat every one of the
following as expected rather than exceptional.

**Symptoms, in the order they show up:**

1. The fetch lands but the load quarantines far more rows than usual.
2. A field that always had a value is suddenly absent across every record.
3. A boolean arrives as a string, or `facility_location.post_code` — which
   arrives as an **integer**, not a string — changes type again.
4. Nothing visibly breaks and a venue card just starts giving a wrong answer.
   This is the dangerous one.

**What to do:**

```bash
# 1. Get the landed body and look at it, rather than guessing from a stack trace.
aws s3 ls s3://sportable-staging-raw-725699850301/aaaplay/ --recursive | tail -5
aws s3 cp s3://sportable-staging-raw-725699850301/aaaplay/dt=YYYY-MM-DD/aaaplay.json .

# 2. What keys exist now, and on how many records? The document is
#    {"source_id", "base_url", "post_types": {activity, facility, organisation},
#     "taxonomies": {activity_type, age_range, lga, region}}.
python3 -c "import json,collections; d=json.load(open('aaaplay.json')); \
  rows=d['post_types']['facility']; print(len(rows)); \
  print(collections.Counter(k for r in rows for k in (r.get('acf') or {})).most_common())"

# 3. Compare against the previous week's object. The bucket is versioned.
aws s3api list-object-versions --bucket sportable-staging-raw-725699850301 \
  --prefix aaaplay/ --query 'Versions[].[Key,LastModified,VersionId]' --output table
```

**Then decide by the rule, not by what makes the load pass:**

- **A new field is not evidence.** Nothing from this source may write to `venue`,
  `venue_amenity_status` or `venue_access_chain`
  ([ADR-006](../adr/ADR-006-provider-claims-are-not-confirmed.md)). A new
  accessibility boolean is a provider claim on arrival and stays one.
- **A removed field is `no_published_information`, never `not_available`.** That
  is AC4.2.3, and it is the same rule as an unticked checkbox.
- **A retyped field is a transformer change and a test**, not a cast bolted into
  the loader. There are 42 tests on DS-09 and they run without network or
  database; add to them.
- **Update the card in the same change.** `data/sources/DS-09_aaaplay.yaml` is
  the record of what the source publishes. A field set that has moved and a card
  that has not is how a wrong answer survives review.

**Log the shape each run** was scoped under I7 and is still not built. Until it is, a field
appearing or changing type is discovered through a wrong answer on a venue card
rather than through a log line — which is exactly the failure mode the task
exists to close.

---

# I need to look at the database

The database has no public IP and there is no NAT Gateway
([ADR-002](../adr/ADR-002-gateway-endpoint-over-nat.md)). **The bastion is the
only route in.** Both it and the database are normally stopped.

```bash
# 1. Start both. RDS takes 3-5 minutes; the bastion about 30 seconds.
aws rds start-db-instance --db-instance-identifier sportable-staging-db
aws ec2 start-instances --instance-ids "$(terraform output -raw bastion_instance_id)"

# 2. Wait for the database.
aws rds wait db-instance-available --db-instance-identifier sportable-staging-db

# 3. Get the tunnel command. The bastion's public IP CHANGES every restart,
#    so read it now rather than reusing one you saved.
terraform output -raw db_tunnel_command

# 4. Run that in its own terminal and leave it open. Then, in another:
psql "$(aws ssm get-parameter --name /sportable/staging/db/url \
        --with-decryption --query Parameter.Value --output text \
        | sed 's#@[^:]*:5432#@localhost:5433#')"
```

Two things that will catch you:

- **Port 5433, not 5432.** A system PostgreSQL already owns 5432 on most of our
  laptops. Stop the local PostGIS container first or the tunnel silently
  attaches to the wrong thing.
- **SSH will be refused if your home IP has changed.** The security group admits
  one address. Update `allowed_ssh_cidrs` in `terraform.tfvars` and apply.
  **Never widen it to `0.0.0.0/0`** — the variable has a validation rule that
  rejects that, deliberately.

## When you are finished — this is not optional

```bash
aws rds stop-db-instance --db-instance-identifier sportable-staging-db
aws ec2 stop-instances --instance-ids "$(terraform output -raw bastion_instance_id)"
```

Left running, these two are essentially the entire cost of the project. There
is **no budget alarm** — `budgets:ModifyBudget` is denied to us — so nothing
will tell you.

---

# Run the loader by hand over the tunnel

`data/scripts/load_run.py` runs transform and load against a live database. It
**cannot run in CI** — the database is in a private subnet with no route from the
internet, by design ([ADR-002](../adr/ADR-002-gateway-endpoint-over-nat.md)). A
laptop plus the bastion tunnel is the only way to drive it by hand.

Bring the tunnel up first — see *I need to look at the database*, above — then:

```bash
cd data
export DATABASE_URL="$(aws ssm get-parameter --name /sportable/staging/db/url \
    --with-decryption --query Parameter.Value --output text \
    | sed 's#@[^:]*:5432#@localhost:5433#')"

uv run python scripts/load_run.py --seed-sources
uv run python scripts/load_run.py DS-06 DS-07 DS-08 DS-01 DS-02 DS-04 --raw ./_raw
uv run python scripts/load_run.py DS-01 --derive
```

`DATABASE_URL` unset exits immediately and points you back here. A URL that does
not mention `localhost` prints a warning and continues — it is asking whether you
meant to skip the tunnel, not stopping you.

## The order is not a preference

`clip_to_scope` refuses to run while the `lga` table is empty, with the error
*"The LGA boundary layer is empty, so scope cannot be decided."* So: seed
`source` first, because it is a foreign-key target for everything else, then
DS-06 boundaries, then DS-01 venues, then the amenity sources. `--derive`
rebuilds `venue_amenity_status` and `venue_access_chain` after loading.

## `--scope`, and why it is the most dangerous flag in the file

**The default is the whole of Victoria, expressed as an empty set.**

```python
DEFAULT_SCOPE: set[str] = set()
```

Empty means *every Victorian council in the DS-06 layer*. It is empty rather
than a list of roughly eighty names deliberately: a list would go stale the next
time the ABS renames a council, **and it would go stale silently, by quietly
dropping that council's venues**.

`--scope` takes normalised LGA names and narrows that. Three things about it
that are easy to get wrong:

**1. It narrows every source, not just venues.** DS-06 *sets* the flag and takes
`--scope` directly. Everything else *reads* the flag back out of the database
through `scope_from_database()`. So a narrowed DS-06 load silently changes what
"in scope" means for toilets and parking as well as for venues, on every
subsequent load, until DS-06 is loaded again wide.

**2. It only takes effect on a DS-06 load.** Passing `--scope` alongside DS-01
does nothing — DS-01 is filtered against whatever was flagged the last time
DS-06 ran, which may have been a different run on a different day. That is
intentional: one definition of scope, in the table.

**3. `ds01.transform` drops out-of-scope rows, it does not quarantine them.** An
empty scope set therefore produces an empty load, **and an empty load looks
exactly like a source that published nothing.** The script guards this and exits
rather than proceeding:

```
No LGA is flagged in scope, so every venue would be dropped.
Load DS-06 first: uv run python scripts/load_run.py DS-06
```

**Narrow scope with `--scope`, deliberately, and never by editing
`DEFAULT_SCOPE`.** The column that carries the flag is still called
`in_greater_melbourne` and now means "in scope" — that misnomer, and the
statewide change behind it, are
[ADR-004](../adr/ADR-004-victorian-scope-over-greater-melbourne.md).

## Two things the wider scope changed that will look like bugs

- **Venue counts jumped from 129 to 3,896.** That is the scope change, not a
  duplicate load.
- **Venues outside the City of Melbourne have no accessible parking record at
  all**, because DS-04 is published by that one council for its own area. The
  product shows this as *"no published information"*, never as an absence of
  parking. Do not go looking for the missing rows; they were never published.

## Other flags

| Flag | What it does |
|---|---|
| `--raw` | Where the raw zone lives locally. Defaults to `data/_raw` |
| `--seed-sources` | Populates the `source` table. Run once, first |
| `--derive` | Builds `venue_amenity_status` and `venue_access_chain` after loading |
| `--gtfs-modes` | DS-03 only. Mode directory numbers, e.g. `1 2 3`. Omit to read every mode |

---

# Rotate the database credential

Do this if the password may have been exposed — pasted into a chat, committed,
or read by someone who should not have it.

The password is generated by Terraform (`random_password.master`) and feeds
three things: the RDS instance, `/sportable/staging/db/password`, and
`/sportable/staging/db/url`. Rotating means replacing that one resource.

```bash
cd infra/envs/staging
terraform plan -replace='module.database.random_password.master'   # READ THIS
terraform apply -replace='module.database.random_password.master'
```

The instance has `apply_immediately = true`, so RDS takes the new password at
once rather than waiting for the maintenance window.

### The part that is easy to get wrong

**The API will still hold the old connection string after that apply.**

`modules/api` reads the URL through `data "aws_ssm_parameter" "db_url"`. A data
source whose name is already known is read during **plan**, before the apply
writes the new value — so the function is configured with the value from
*before* the rotation. It lags by exactly one apply.

Then, separately, the `live` alias does not follow a newly published version;
moving it is the pipeline's job.

**So the procedure is: rotate, then deploy, then verify.**

```bash
gh workflow run deploy-staging.yml --ref dev     # picks up the new URL, moves the alias
gh run watch
curl -s https://d1nsbukoi7bexf.cloudfront.net/api/v1/health
```

Today this is harmless — the stub handler serves fixtures and never opens a
connection. **It stops being harmless the moment the real handler lands**, so
rotate before that, or expect to run the pipeline twice.

Never read the password unless you actually need it, and never paste it:

```bash
aws ssm get-parameter --name /sportable/staging/db/password --with-decryption \
  --query Parameter.Value --output text
```

---

# Change a setting without changing code

The distance bands, the default radius and the staleness thresholds live in
Parameter Store, not in the handler.

```bash
aws ssm put-parameter --name /sportable/staging/search/distance_bands_m \
  --type StringList --value "250,500,750,1000" --overwrite

gh workflow run deploy-staging.yml --ref dev
curl -s https://d1nsbukoi7bexf.cloudfront.net/api/v1/config
```

The three `search/` parameters carry `ignore_changes = [value]`, so Terraform
sets them once and never reverts your edit. No pull request, no review, no
Python change — but it does need a pipeline run, because the values are read at
apply time rather than at runtime ([ADR-002](../adr/ADR-002-gateway-endpoint-over-nat.md)
explains why).

`"source": "terraform"` in the response means the values came from Parameter
Store. `"source": "fallback"` means they did not, and you are seeing the
committed defaults.

---

# End of day

```bash
aws rds describe-db-instances --query 'DBInstances[].[DBInstanceIdentifier,DBInstanceStatus]' --output text
aws ec2 describe-instances --filters "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType]' --output text
```

Anything listed as `running` or `available` should be stopped unless you know
why it is up.

```bash
aws ce get-cost-and-usage --time-period Start=$(date -u +%Y-%m-01),End=$(date -u -v+1d +%Y-%m-%d) \
  --granularity MONTHLY --metrics UnblendedCost \
  --query 'ResultsByTime[].Total.UnblendedCost.Amount' --output text
```

This is the **manual substitute for a budget alarm**, which we cannot create.
Run it at the end of each working session. Anything above a few cents means
something is running that should not be.

---

# Known traps

Things that have actually happened here, with the fix.

| Symptom | Cause | Fix |
|---|---|---|
| Plan wants to **destroy and recreate the bastion** | Its AMI came from AWS's "latest" pointer, which changes when AWS publishes a new image | Fixed: `ami` is now in `ignore_changes`. Rebuild deliberately with `terraform apply -replace='module.bastion.aws_instance.bastion'` |
| Bastion is running and nobody started it | Same cause — a replacement comes back **running**, with a new public IP | Stop it. Verified fixed 1 Sep 2026 |
| Plan is never clean; one pending change forever | The pipeline sets `cache-control` on `index.html`; Terraform wanted to remove it | Fixed: `cache_control` is in `ignore_changes`. **Do not apply that change** — it would let browsers cache a stale `index.html` |
| SSH to the bastion times out | Home IP changed | Update `allowed_ssh_cidrs` and apply |
| `psql` connects but the data looks wrong | The tunnel is on 5433 and a local PostgreSQL owns 5432 | Stop the local container |
| API returns 500 after a config change | Something in the VPC tried to reach an AWS API | Nothing inside the VPC can reach outside it. Pass the value as an environment variable |
| `terraform output -raw` prints extra formatting | `terraform_wrapper` enabled in the workflow | It is set to `false`; check it was not removed |
| Deploy stops at *Database migrations* | Backend committed the first Alembic revision | Expected and correct. Build the migration Lambda — see `infra/T3-part2-deploy-runbook.md` |
| `aws lambda invoke` returns a parse error on the payload | AWS CLI v2 base64-encodes `--payload` by default | Add `--cli-binary-format raw-in-base64-out`, as in the DS-09 command above |
| A forced DS-09 fetch reports `no_change` | `force` was not in the payload, or was spelled differently | The key is exactly `"force": true`. It is read once per invocation and applies to every id in `source_ids` |
| A DS-09 load run looks fine and the events are a month old | `no_change` is indistinguishable from a healthy quiet week without checking dates | Check `MAX(finished_at)` in `load_run` for DS-09. No alarm catches this: a true freshness alarm exceeds CloudWatch's one-day evaluation window. Check the rule is enabled |
| Venue search returns thousands more rows than it used to | Scope is the whole of Victoria, not the 31 Greater Melbourne councils | Expected since 14 Sep 2026. [ADR-004](../adr/ADR-004-victorian-scope-over-greater-melbourne.md) |

---

# Things only the account holder can do

We hold `PowerUserAccess`, whose policy is `NotAction: ["iam:*", ...]`. Every
IAM write is denied, and so are Budgets. When you need one of these, ask — and
include the exact action name from the error.

| Need | Why we cannot |
|---|---|
| Create or change an IAM role or policy | `iam:*` denied. Both Lambda execution roles were pre-built for us and are hardcoded as ARNs |
| Change the GitHub deploy role's trust policy | `iam:UpdateAssumeRolePolicy` denied |
| Create the USD $5 budget alarm | `budgets:ModifyBudget` denied |
| Raise the Lambda concurrency limit above 10 | AWS Free plan restriction, not a permission |

---

# What this runbook does not cover

- **Restoring the database from a backup.** Retention is 1 day (the Free plan
  cap) and the data is rebuildable by re-running ingestion, so it has never been
  rehearsed. If it matters before submission, rehearse it — an untested restore
  is not a backup.
- **Incident communication.** Six people and a group chat; no process needed.
- **Production.** There is one environment. `envs/prod/` is an empty placeholder,
  and CI only validates `envs/staging`.

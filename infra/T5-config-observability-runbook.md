# T5 — Configuration and Observability Runbook

**SportAble Melbourne** · FIT5120 · Iteration 1 · Infra/Platform owner: Charan

| | |
|---|---|
| **Task** | T5 — *Make the distance limits configurable and the system observable* (4.0 h) |
| **Serves** | US1.2 / AC1.2.4 — *"choose 250 m, 500 m or 1 km"* · AC1.3.2 — source currency |
| **Depends on** | T1 (RDS), T2 (Lambda, API Gateway), T3 (the pipeline that applies it) |
| **Written** | 30 Aug 2026 |
| **Status** | Applied 30 Aug. Alarms live; SNS subscription **unconfirmed**. Runtime SSM read failed and was replaced — see below. |

---

## The sentence that defines done

> **You break something on purpose and an email arrives.**

Not "a dashboard exists." A dashboard is something you have to remember to look
at, and nobody looks at one during an assessment week. An alarm comes to you.

Everything in this task is judged against that sentence.

---

## One thing was already done

All three log groups already carry **explicit 14-day retention**:

```
/aws/apigateway/sportable-staging-api          14
/aws/lambda/sportable-staging-api              14
/aws/rds/instance/sportable-staging-db/postgresql   14
```

That was set in T1 and T2, deliberately, in the module that owns each resource
— `modules/api` and `modules/database` both create the log group **before** the
thing that writes to it.

The ordering is the whole point. Let Lambda create its own log group implicitly
and it defaults to **never expire**: the logs quietly consume the 5 GB free tier
and then bill forever, and by the time anyone notices there is no way to
retroactively not have stored them.

---

## Part 1 — Configuration in Parameter Store

### The problem

AC1.2.4 lets a user choose 250 m, 500 m or 1 km. Those three numbers have to
live somewhere. The tempting place is the handler:

```python
DISTANCE_BANDS = [250, 500, 1000]  # do not do this
```

Then *"make 750 m an option"* becomes a code change, a pull request, a CI run
and a deploy. Here it is one `put-parameter` and a pipeline run.

That matters most in the demo. If a marker asks *"what if the corridor were
wider?"*, the answer should be a shrug and about a minute — not *"that's a code
change."*

### The tree

```
/sportable/staging/
├── db/                                    ← T1. Credentials.
│   ├── host                String
│   ├── name                String
│   ├── password            SecureString   ← a real secret
│   └── url                 SecureString
├── search/                                ← T5. Product settings.
│   ├── distance_bands_m    StringList     "250,500,1000"
│   ├── default_distance_m  String         "500"
│   └── max_results         String         "100"
└── data/staleness_days/                   ← T5. AC1.3.2.
    ├── vic_sport_rec       String         "14"
    ├── public_toilets_nptm String         "14"
    ├── ptv_gtfs            String         "14"
    └── osm                 String         "45"
```

### Three decisions worth understanding

**Parameter Store, not Secrets Manager.** None of this is secret. Secrets
Manager charges USD $0.40 per secret per month and exists for values that need
rotation. Standard parameters are free, versioned, and auditable through
CloudTrail.

**Plaintext, not SecureString — and checkov disagrees.** `CKV2_AWS_34` fails on
all seven of these. The skip is documented in the resource rather than waved
through, because the reasoning is the interesting part: a SecureString would add
a KMS decrypt to every cold start and hide values that are *meant* to be
readable at a glance. The contrast with `db/password` in the same tree is
deliberate — that one genuinely is a secret.

**Staleness thresholds are longer than the publisher's cadence.** The three
weekly feeds get 14 days; OSM, which publishes monthly, gets 45. Set them equal
to the cadence and one missed refresh — a public holiday, a portal outage —
marks the data stale and the UI starts apologising for data that is fine.

### The read path — and the mistake that shaped it

Configuration nobody reads is decoration, so `/api/v1/config` was added to the
handler. **The first version read Parameter Store at cold start, and it timed
out in production.**

```
REPORT RequestId: 62268d62...  Duration: 10000.00 ms  Status: timeout
GET /api/v1/config  ->  {"message":"Internal Server Error"}
```

**Why.** The API Lambda runs in a private subnet. Its route table holds exactly
two entries:

```
10.0.0.0/16   local
(prefix list) vpce-0314d5ffda7b3d0d6      <- S3 gateway endpoint
```

No default route. No path to `ssm.ap-southeast-2.amazonaws.com`. The SDK call
did not fail — it **hung**, until the 10 s function timeout turned the whole
request into a 500.

Two lessons, and the second is the transferable one:

1. The same constraint that stops a CI runner reaching RDS stops the Lambda
   reaching SSM. It had already been written down for migrations in the T3
   runbook and was not applied in the other direction.
2. **A `try/except` around a network call is not a safety net.** It catches
   failures; a hang is not a failure. Defensive code around I/O has to bound
   the *time*, not just catch the exception.

### The fix: read at apply time, not at runtime

Reaching SSM from inside the VPC needs an **interface** endpoint — roughly
USD $9.49/month per AZ, more than this project's entire budget target, to save
about a minute on a config change.

So the read moved to the CI runner, which has ordinary internet access — exactly
how `DATABASE_URL` already worked:

```hcl
data "aws_ssm_parameters_by_path" "search" {
  path = "${var.ssm_prefix}/search"
}
# ... passed to the function as one JSON environment variable
SEARCH_CONFIG = jsonencode(zipmap(...))
```

The handler now parses an environment variable and **makes no network call at
all**. Parsing a string cannot time out.

**What this costs, stated plainly:** changing a band is no longer live. It takes
a pipeline run, about a minute.

**What it does not cost:** it is still not a code change. The three search
parameters carry `lifecycle { ignore_changes = [value] }`, so Terraform sets
them once and then leaves them to operators. The whole procedure is:

```bash
aws ssm put-parameter --name /sportable/staging/search/distance_bands_m \
  --type StringList --value "250,500,750,1000" --overwrite
gh workflow run deploy-staging.yml --ref dev
```

No PR, no reviewer, no edit to a Python file. That was the point of T5, and it
survives.

### The response

```
GET https://d1nsbukoi7bexf.cloudfront.net/api/v1/config

{"distance_bands_m": [250, 500, 1000],
 "default_distance_m": 500,
 "max_results": 100,
 "source": "terraform"}
```

- **It is not a fixture.** Every other endpoint returns `_fixture: true`. This
  one carries live values, so the Frontend renders AC1.2.4's choices without
  hardcoding them.
- **`source` is the diagnostic.** `"terraform"` means the values came from
  Parameter Store via the last apply. `"fallback"` means `SEARCH_CONFIG` was
  missing or unparseable and the committed defaults are being served — still the
  right answer, but not a live one.

---

## Part 2 — Six alarms

No dashboard, no X-Ray, no custom metrics. Six alarms on metrics AWS already
publishes for free. Each answers a question someone would actually ask at 2am,
and none fires on a healthy system — **an alarm that cries wolf is worse than no
alarm**, because the team learns to delete the email unread.

| Alarm | Fires when | Why it earns its place |
|---|---|---|
| `lambda-errors` | ≥ 1 error in 5 min | On a system serving a handful of demo requests, one error is a real proportion of traffic. Waiting for five means waiting for a pattern that may never form before the demo. |
| `lambda-throttles` | ≥ 1 throttle in 5 min | This account's **total** concurrency limit is 10 and the Free plan will not raise it. Six people clicking during a live demo is a realistic way to hit it. |
| `lambda-duration` | avg > 8 s over 2 periods | Warns *before* the 10 s timeout starts cutting requests off. Almost always a database connection hanging rather than failing fast. |
| `api-5xx` | ≥ 1 in 5 min | Server errors only. |
| `rds-connections` | max > 40 over 2 periods | `db.t4g.micro` allows ~112. Lambda holds one connection per execution environment, so a handler that forgets to release them climbs steadily until the database refuses everything at once. |
| `rds-free-storage` | < 2 GB | 20 GB allocated with autoscaling deliberately off, so this does not fix itself. |

### Three details that are easy to get wrong

**`5xx`, not `5XXError`.** HTTP APIs publish `5xx`. `5XXError` is the REST API
metric name, and using it produces an alarm that looks perfect and silently
never fires.

**4xx is deliberately not alarmed.** Our own smoke test requests a nonexistent
venue on every deploy. Alarming on 4xx would page us for a passing test.

**`treat_missing_data = "notBreaching"` everywhere.** Two reasons. No
invocations publishes no datapoints, so without it every alarm sits in
`INSUFFICIENT_DATA` overnight and you cannot tell *quiet* from *broken*. And RDS
is stopped most evenings to save money — "missing" must not read as "breaching",
or the team gets an email every night for doing the right thing.

**`ok_actions` are set too.** You get the recovery email, not just the failure.
An alarm you never see clear is an alarm you start ignoring.

---

## The SNS trap — read this one

Terraform creates the email subscription. **AWS then sends a confirmation link
that a human must click.** Until someone clicks, that address receives nothing.

Terraform reports success either way, because the subscription resource
genuinely was created. `terraform show` cannot tell you the difference. This is
the single most common way a team discovers, mid-incident, that their alerting
never worked.

**Verify every time you change `alert_emails`:**

```bash
export AWS_PROFILE=sportable
aws sns list-subscriptions-by-topic \
  --topic-arn "$(cd infra/envs/staging && terraform output -raw alerts_topic_arn)" \
  --query 'Subscriptions[].[Endpoint,SubscriptionArn]' --output table
```

A `SubscriptionArn` of literally `PendingConfirmation` means that address is
deaf. Only a real ARN counts.

`alert_emails` currently holds one address. Add teammates only if they have
agreed to receive alarm mail — unwanted alarm mail gets filtered, and a filtered
alarm is the same as no alarm.

---

## Applying it

The plan, verified locally:

```
Plan: 15 to add, 1 to change, 0 to destroy.
```

The one change is the Lambda picking up its new `SSM_PREFIX` environment
variable (and the drill revert). All 15 additions are new.

CI parity, all run locally before pushing:

```
terraform fmt -check -recursive   clean
terraform validate                Success
tflint --recursive                exit 0
checkov -d infra                  136 passed, 0 failed, 53 skipped
ruff / ruff format / mypy         clean
pytest                            17 passed
```

Let the pipeline apply it — that is what T3 is for. A push to `dev` does the
whole thing.

---

## Testing it: break something on purpose

This is the deliverable, not a formality.

### 1. Confirm the subscription

Check your inbox for *"AWS Notification - Subscription Confirmation"* and click
the link. Then run the verification command above and confirm you see a real
ARN.

### 2. Cause a genuine Lambda error

No deploy needed. The handler indexes `rawPath` as a string, so a non-string
value raises:

```bash
export AWS_PROFILE=sportable
aws lambda invoke --function-name sportable-staging-api \
  --payload '{"rawPath": 123}' --cli-binary-format raw-in-base64-out \
  /dev/stdout
```

This produces a real unhandled exception — the same signal a genuine bug would
— without deploying anything or touching the `live` alias.

### 3. Wait

Roughly **five to eight minutes**: a minute or two for the metric to publish,
then up to five for the alarm's evaluation period.

```bash
aws cloudwatch describe-alarms --alarm-names sportable-staging-lambda-errors \
  --query 'MetricAlarms[].[StateValue,StateReason]' --output text
```

`ALARM` here and an email in your inbox is T5 complete. A second email follows
when it returns to `OK`.

### 4. Record it

Note the date and the alarm that fired. T6 asks for evidence, and "we tested it"
without a timestamp is indistinguishable from "we meant to."

---

## What is blocked

**The budget alarm at USD $5 is not built.** `budgets:ModifyBudget` is
explicitly denied to `teammate_deploy`, so only the account holder can create
it. Cost Anomaly Detection is deliberately left out of Terraform for the same
reason — a resource that fails mid-apply is worse than one that was never
attempted.

Send this:

> Could you add a Budgets alarm on account 725699850301? USD $5 monthly, alert
> at 80% and 100% actual, notifying `crag0006@student.monash.edu`. I hold
> `ce:GetCostAndUsage` so I can check spend manually, but nothing tells me
> automatically if something is left running.

Until then, the manual substitute — worth running at the end of each working
session:

```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-08-01,End=2026-08-31 \
  --granularity MONTHLY --metrics UnblendedCost \
  --query 'ResultsByTime[].Total.UnblendedCost.Amount' --output text
```

Month-to-date at the time of writing: **$0.0000000007**.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/api/v1/config` returns `"source": "fallback"` | `SEARCH_CONFIG` missing or unparseable — usually a deploy that predates it | Re-run the pipeline. Values stay correct meanwhile |
| `/api/v1/config` returns 500 | A runtime SDK call was reintroduced | The handler must make no network call. See "the mistake that shaped it" |
| No email when an alarm fires | Subscription still `PendingConfirmation` | Click the link in the AWS email, then re-run the verification command |
| Alarms stuck in `INSUFFICIENT_DATA` | Missing `treat_missing_data` | It is set to `notBreaching` on all six — check it was not removed |
| `api-5xx` never fires despite real 5xxs | Metric name is `5XXError` | HTTP APIs publish `5xx`. Different from REST APIs |
| Alarm email every night | RDS stopped, alarm treating missing as breaching | Same `notBreaching` setting; RDS is stopped deliberately |
| checkov fails on `CKV2_AWS_34` | A skip was removed or moved outside the resource block | The comment must be **inside** the block, and the reason after the colon is mandatory |
| Changing a band did not change the UI | Lambda still warm on the old cold-start cache | Cache is per execution environment. Wait, or force a new one by redeploying |

---

## Definition of done

- [x] SSM hierarchy under `/sportable/staging/` — bands, default, max results, four staleness thresholds
- [x] Read by Terraform at apply time and injected; handler makes no network call
- [x] `/api/v1/config` so the Frontend never hardcodes AC1.2.4's choices
- [x] Log groups with explicit 14-day retention (done in T1/T2)
- [x] Six CloudWatch alarms — Lambda errors, throttles, duration; API 5xx; RDS connections, storage
- [x] SNS topic with `ok_actions` as well as `alarm_actions`
- [x] All CI checks pass locally, including checkov with documented skips
- [x] Applied via the pipeline — 15 resources, run `33305847774`
- [ ] Subscription confirmed — a real ARN, not `PendingConfirmation`
- [ ] **An alarm broken on purpose and an email received**, with the date recorded
- [ ] Budget alarm — account holder

---

## Notes for T4

`module.observability` outputs `topic_arn`. The ingestion alarms in T4 —
*"alarm after three failures"* — should publish to that same topic rather than
creating a second one. One place to confirm a subscription, one place to look
when the email arrives.

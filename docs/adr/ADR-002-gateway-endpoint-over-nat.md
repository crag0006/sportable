# ADR-002 — An S3 Gateway Endpoint instead of a NAT Gateway

| | |
|---|---|
| **Status** | Accepted |
| **Date decided** | 30 August 2026 |
| **Date recorded** | 1 September 2026 |
| **Decider** | Charan — Infrastructure / Platform |
| **Affects** | Every component that runs inside the VPC, and three later decisions |

---

## Context

The database has no public IP and must not have one. Anything that queries it
therefore has to run **inside the VPC**, in a private subnet.

A Lambda function in a private subnet starts with no route to anywhere except
the VPC itself. It cannot reach the internet, and — the part that surprises
people — it cannot reach **AWS's own public service endpoints** either. S3,
Parameter Store and every other AWS API are reached over public addresses.

Our code needs to reach S3. The standard answer is a NAT Gateway.

The budget makes that answer worth questioning: the account has about USD $120
of credit and no budget alarm, because `budgets:ModifyBudget` is denied to us.
Overspend would be discovered by looking, not by being told.

## Options considered

Prices verified **1 September 2026** against the AWS Pricing API for
`ap-southeast-2`, at 730 hours per month.

| Option | Monthly, idle | Per GB | Gives us |
|---|---:|---:|---|
| **NAT Gateway** | **$43.07** | $0.059 | Full outbound internet from private subnets |
| **Interface endpoint**, per service, per AZ | **$9.49** | $0.004–0.010 | One AWS service, privately |
| **S3 Gateway Endpoint** | **$0.00** | **$0.00** | S3 only, privately |
| Lambdas outside the VPC | $0.00 | — | Internet, but **no database access** — disqualifying |

> **Correcting the record.** The task plan estimated ~$32/month for the NAT
> Gateway and `infra/README.md` said ~$40. Both were US East rates. Sydney is
> **$0.059/hour**, so the real idle cost is **$43.07/month** — more than a third
> of the project's entire credit, to run a component nothing would have used on
> a hot path.

## Decision

**An S3 Gateway Endpoint. No NAT Gateway. No default route in the private route
table.**

The private route table has exactly two entries, and this is the whole design in
four lines:

```
10.0.0.0/16    local                      the VPC talking to itself
(prefix list)  vpce-0314d5ffda7b3d0d6     S3, privately and free
```

There is no `0.0.0.0/0`. Nothing else is reachable, in either direction.

## Consequences

### What this bought

**$43.07 a month, on a budget with no alarm.** Month-to-date spend at the time
of writing is $0.0000000007.

**Security by absence rather than by rule.** The database is unreachable from
the internet because **no path exists**, not because a rule forbids it. Rules
get edited by someone in a hurry; a missing route does not. This is also why the
Definition of Done includes, as a checkable fact, *"no NAT Gateway has ever been
created."*

### What it cost — the honest part

This decision broke three things later. None was predicted; all three are worth
recording, because the pattern is the same each time.

**1. Database migrations cannot run from CI.**
A GitHub runner has no network path to RDS. `alembic upgrade head` in the deploy
pipeline is impossible. The pipeline's migration step is deliberately
**fail-closed**: it passes while no revisions exist, and stops the deploy —
before the alias moves — the day the first one lands. The fix is a migration
Lambda inside the VPC, not a NAT Gateway.

**2. The API could not read Parameter Store at runtime, and returned 500.**
The handler called Parameter Store at start-up, wrapped in a `try/except` that
would fall back to defaults. It did not fall back. **The call did not fail — it
hung**, until the ten-second function timeout turned the request into a 500:

```
REPORT RequestId: 62268d62…  Duration: 10000.00 ms  Status: timeout
```

A `try/except` catches failures. A hang is not a failure. The read moved to the
deployment pipeline, which runs on an ordinary machine with ordinary internet,
and the values are passed to the function as an environment variable. **Parsing
a string cannot time out.**

**3. Ingestion needs two Lambda functions rather than one.**
The fetch step must reach public data portals, so it runs *outside* the VPC. The
load step must reach RDS, so it runs *inside* and gets to S3 through this
endpoint. One function could not be both.

### The rule to internalise

> **In this VPC, nothing inside can reach anything outside.**

Ask which side of that line a component belongs on **before** writing it, not
after it times out. All three consequences above are the same mistake made
three times, and each one cost an afternoon.

## Revisit when

Something genuinely needs an AWS service from inside the VPC on a hot path.

Price a **single interface endpoint for that one service** — $9.49/month —
before anyone reaches for a NAT Gateway at $43.07. The two decisions are not
close, and the cheaper one is also the narrower one.

Two candidates already exist and were both declined for now:

- **Parameter Store**, so the API could read configuration live. Declined: the
  apply-time read costs nothing and a settings change still needs no code
  change, only a pipeline run of about a minute.
- **Secrets Manager**, if credential rotation ever becomes automatic. Not in
  Iteration 1.

## See also

- [ADR-001](ADR-001-terraform-over-cdk-and-sam.md) — how any of this gets built
- `infra/modules/network/main.tf` — the endpoint and the route table
- `infra/modules/api/main.tf` — the apply-time read, and why it is not at runtime
- `.github/workflows/deploy-staging.yml` — the fail-closed migration step

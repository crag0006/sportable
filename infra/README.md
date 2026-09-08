# Infrastructure — SportAble Melbourne

Terraform 1.9+ (OpenTofu-compatible). Owner: Infra/Platform engineer.

## Layout

| Path | Purpose |
|---|---|
| `bootstrap/` | One-off: S3 state bucket with native locking. Run manually, with local state, committed once. **No DynamoDB table** — see below. |
| `modules/iam_oidc/` | GitHub OIDC provider + deploy role. No long-lived AWS keys anywhere. |
| `modules/network/` | VPC 10.0.0.0/16, private subnets az-a/az-b, **S3 Gateway Endpoint (no NAT Gateway)**. |
| `modules/database/` | RDS PostgreSQL 16, db.t4g.micro, PostGIS 3, private subnet group, no public IP. |
| `modules/static_site/` | S3 SPA bucket + CloudFront (OAC) + ACM certificate. |
| `modules/api/` | API Gateway HTTP API + Lambda (FastAPI via Mangum) + execution role. |
| `modules/ingestion/` | EventBridge rules, Fetch Lambda (outside VPC), Transform/Load Lambda (inside VPC), S3 raw zone, quarantine bucket. |
| `modules/observability/` | CloudWatch log groups, metric filters, alarms, SSM parameters. |
| `envs/staging/` | The only environment for Iteration 1. |
| `envs/prod/` | Scaffolded, not applied until Iteration 2 (build URL freeze). |

## The one rule that matters most

**Never provision a NAT Gateway.** USD $43.07/month in `ap-southeast-2`
($0.059/hour x 730, verified against the AWS Pricing API on 1 Sep 2026, plus
$0.059/GB processed). Earlier drafts said ~$32 and ~$40 — both were US East
rates. See [ADR-002](../docs/adr/ADR-002-gateway-endpoint-over-nat.md).
before a byte of data crosses it — more than every other resource in this
project combined. The S3 Gateway Endpoint in `modules/network` exists precisely
so that no in-VPC Lambda ever needs one. It is a route-table entry, not a
server, and costs nothing.

Every resource is checked for cost before adoption. The single planned
exception is Amazon Bedrock in Iteration 3.

See [Cost control](#cost-control-while-there-is-no-budget-alarm) below for what
to stop, and [the Free plan](#the-aws-free-plan-restricts-capabilities-not-just-spend)
for the restrictions this account carries.

## State locking — why there is no DynamoDB table

DynamoDB never stored Terraform state. It was a mutex: a lock needs an atomic
test-and-set, and S3 historically could not express "create this object only if
it does not already exist", so Terraform borrowed that one primitive from
DynamoDB.

S3 has supported conditional writes since 2024. The S3 backend now takes
`use_lockfile = true` and holds the lock as an object beside the state, and
HashiCorp's documentation marks `dynamodb_table` **deprecated and slated for
removal**. Verified against the S3 backend documentation on 28 Aug 2026.

Practical consequence for the deploy role's IAM policy: it needs
`s3:ListBucket` on the bucket, `s3:GetObject` and `s3:PutObject` on the state
key, plus `s3:DeleteObject` on the **lock file** path. The state object itself
never needs delete permission.

## Local toolchain

```bash
brew install tfenv && tfenv install latest && tfenv use latest
brew install pre-commit
uv tool install checkov
```

`tflint` is not in Homebrew core. Install the release binary and verify its
checksum:

```bash
curl -sLo tflint.zip https://github.com/terraform-linters/tflint/releases/download/v0.64.0/tflint_darwin_arm64.zip
curl -sLo checksums.txt https://github.com/terraform-linters/tflint/releases/download/v0.64.0/checksums.txt
grep tflint_darwin_arm64.zip checksums.txt | shasum -a 256 -c -
unzip -o tflint.zip && mv tflint ~/.local/bin/ && rm tflint.zip checksums.txt
tflint --init && tflint --version    # should list ruleset.aws
```

> **macOS note.** If `tfenv use` fails with a path under `~/.config/tfenv`, that
> directory is root-owned on some machines. Add
> `export TFENV_CONFIG_DIR="$HOME/.tfenv"` to your shell profile.

## Working on Terraform

```bash
terraform fmt -recursive infra          # format
tflint --recursive --chdir=infra        # provider-aware lint
checkov -d infra --framework terraform  # security policy scan
```

CI runs all three on every pull request, plus `terraform validate`. The
Terraform job currently skips itself because `infra/` holds only placeholders;
it activates automatically when the first `.tf` file is committed.

## The AWS Free plan restricts capabilities, not just spend

The staging account is on the AWS Free plan (the credit-based model). That plan
**blocks certain features and resource types outright**, regardless of whether
you are willing to pay for them.

None of these are visible to `terraform validate`, `tflint` or `checkov` — they
only surface when the AWS API rejects the apply. Three were hit while building
T1:

| Attempted | Error | Resolution |
|---|---|---|
| RDS `backup_retention_period = 7` | `FreeTierRestrictionError: The specified backup retention period exceeds the maximum available to free tier customers` | Reduced to `1` |
| Bastion on `t4g.nano` | `InvalidParameterCombination: The specified instance type is not eligible for Free Tier` | Changed to `t4g.micro` |
| RDS `engine_version = "16.4"` | `Cannot find version 16.4 for postgres` | Only 16.9–16.15 are offered; pinned `16.10` |

**How to recognise one:** the message says `FreeTierRestrictionError`, or
mentions Free Tier eligibility. That is the plan refusing — not a mistake in
your Terraform. Do not debug the configuration.

**Check before you write the resource, not after:**

```bash
# EC2 instance types this account may launch at all
aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true \
  --query 'InstanceTypes[].[InstanceType,ProcessorInfo.SupportedArchitectures[0]]' --output table

# RDS engine versions actually available
aws rds describe-db-engine-versions --engine postgres \
  --query 'DBEngineVersions[?starts_with(EngineVersion, `16.`)].EngineVersion' --output table

# RDS instance classes orderable for a given version, and their storage types
aws rds describe-orderable-db-instance-options --engine postgres \
  --engine-version 16.10 --db-instance-class db.t4g.micro \
  --query 'OrderableDBInstanceOptions[].StorageType' --output text
```

Eligible EC2 types on this account, 29 Aug 2026: `t4g.micro`, `t4g.small`,
`t3.micro`, `t3.small`, `c7i-flex.large`, `m7i-flex.large`. The list changes;
re-run the command rather than trusting this line.

**Expect more of these in T2 and T4.** Lambda, CloudFront and API Gateway all
have plan-level limits of their own.

## Cost control while there is no budget alarm

`budgets:ModifyBudget` is explicitly denied on the deploy user, so the usual
guard does not exist. Two habits replace it.

**Stop what you are not using.** Nothing in the network layer costs anything —
VPCs, subnets, route tables, security groups and Gateway endpoints are all free.
The database and the bastion are the only billable resources:

```bash
aws rds stop-db-instance --db-instance-identifier sportable-staging-db
aws ec2 stop-instances --instance-ids $(terraform output -raw bastion_instance_id)
```

Roughly USD $25/month running, ~$3 stopped. A stopped RDS instance restarts
itself after 7 days; stop it again when it does.

**Check spend directly.** `ce:GetCostAndUsage` is permitted:

```bash
aws ce get-cost-and-usage --time-period Start=2026-08-01,End=2026-09-01 \
  --granularity MONTHLY --metrics UnblendedCost \
  --query 'ResultsByTime[0].Total.UnblendedCost.[Amount,Unit]' --output text
```

Each call costs USD $0.01, so check every couple of days rather than in a loop.

> The bastion's public IP **changes on every stop/start**. After starting it,
> run `terraform refresh` then `terraform output bastion_public_ip` — Terraform's
> stored value is stale until you do.

## Documents

- [CI/CD runbook](T3-cicd-runbook.md) — the pipeline, step by step
- [Repository README](../README.md) — team setup and everyday workflow

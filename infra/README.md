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

## Cost guard

Every resource is checked against AWS Free Tier before adoption.
The single deliberate exception is Amazon Bedrock (Iteration 3, Assistant epic).

**Never provision a NAT Gateway.** ~USD $32/month, not Free Tier, and the
S3 Gateway Endpoint in `modules/network` exists precisely to avoid it.

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

## Documents

- [CI/CD runbook](T3-cicd-runbook.md) — the pipeline, step by step
- [Repository README](../README.md) — team setup and everyday workflow

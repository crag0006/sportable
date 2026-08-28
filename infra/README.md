# Infrastructure — SportAble Melbourne

Terraform 1.9+ (OpenTofu-compatible). Owner: Infra/Platform engineer.

## Layout

| Path | Purpose |
|---|---|
| `bootstrap/` | One-off: S3 state bucket + DynamoDB lock table. Run manually, local state, committed once. |
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

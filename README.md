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

## Branches

`main` ← `release-iteration-{1,2,3}` ← `dev` ← `feature/*`

A push to `dev` deploys itself to release iteration. Nothing is deployed by hand.

## Documents

- [Infrastructure](infra/README.md)
- [Data pipeline](data/README.md)

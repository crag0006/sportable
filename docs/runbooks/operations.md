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

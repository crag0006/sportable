# T1 — Private Spatial Database: Runbook and Primer

**SportAble Melbourne** · FIT5120 · Iteration 1 · Infra/Platform owner: Charan

| | |
|---|---|
| **Task** | T1 — *Store the venue data on a private, spatial database* (10 h) |
| **Serves** | US2.1 · AC2.1.1–2.1.4 — venue card showing every access facility, its distance and its source |
| **Account** | `7256-9985-0301` (team account), region `ap-southeast-2` |
| **Written** | 29 Aug 2026 · Iteration 1 closes Sun 6 Sep |

This document is both a **runbook** (what to execute, in order) and a **primer**
(why each piece exists). Read Part 0 and Part 1 before touching anything.

---

## Where we are

| | |
|---|---|
| ✅ CI pipeline | 4 jobs, `dev` and `main` protected, required checks enforced |
| ✅ Local PostGIS | container on port 5433, Alembic verified end-to-end |
| ✅ OIDC | provider + `sportable-github-deploy` role built by the account holder |
| ⚠️ Trust policy | trailing wildcards still too broad — chase, but not blocking |
| ⏭️ **This task** | the VPC, the database, and the way your team reaches it |

**Why T1 next:** T2 (API), T4 (ingestion) and T5 (observability) all sit on top
of its VPC and database. It is the only thing on the critical path, and it needs
no IAM permissions at all — pure PowerUser territory, so nothing here is blocked.

---

# Part 0 — Preparation (do this first, ~20 min)

## 0.1 Create your access key and a named profile

In the console: **top-right account menu → Security credentials → Create access
key** → *Command Line Interface (CLI)* → confirm → download the CSV.

Then:

```bash
aws configure --profile sportable
#   AWS Access Key ID:      AKIA...
#   AWS Secret Access Key:  ...
#   Default region name:    ap-southeast-2
#   Default output format:  json
```

**Use a named profile, never `default`.** You now have three AWS accounts. The
`default` profile still points at your old one, and a mistyped command against
the wrong account is the classic way to lose an afternoon.

```bash
export AWS_PROFILE=sportable      # PowerShell: $env:AWS_PROFILE = "sportable"
```

Put that line in your shell profile if you like, but say it out loud every time:
**check the account before you apply.**

## 0.2 Pre-flight checks — run these and keep the output

Every one of these is free and read-only. They answer questions we would
otherwise guess at, and a wrong guess here surfaces halfway through an apply.

```bash
# 1. WHO AM I — must print 725699850301. Stop if it does not.
aws sts get-caller-identity

# 2. WHICH AVAILABILITY ZONES exist, and what are they called?
#    RDS needs a subnet group spanning two. AZ names are account-specific.
aws ec2 describe-availability-zones --region ap-southeast-2 \
  --query 'AvailabilityZones[].[ZoneName,ZoneId,State]' --output table

# 3. WHAT IS ALREADY IN THE ACCOUNT — we must not collide with the account
#    holder's resources, and 10.0.0.0/16 must be free.
aws ec2 describe-vpcs --query 'Vpcs[].[VpcId,CidrBlock,IsDefault,Tags]' --output json
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
aws ec2 describe-instances \
  --query 'Reservations[].Instances[?State.Name!=`terminated`].[InstanceId,InstanceType,State.Name]' \
  --output table

# 4. WHICH POSTGRES VERSIONS can we actually order? Do not assume "16".
aws rds describe-db-engine-versions --engine postgres \
  --query 'DBEngineVersions[?starts_with(EngineVersion, `16.`)].EngineVersion' --output table

# 5. IS db.t4g.micro ORDERABLE for that version here? Instance class
#    availability varies by region, engine and version. Use a version that
#    check #4 actually returned — AWS removes minors as they reach end of
#    standard support, and 16.4 is already gone from this account.
aws rds describe-orderable-db-instance-options \
  --engine postgres --engine-version 16.10 \
  --query 'OrderableDBInstanceOptions[?DBInstanceClass==`db.t4g.micro`].[DBInstanceClass,StorageType,AvailabilityZones[].AvailabilityZone]' \
  --output json

# If db.t4g.micro returns nothing, retry with db.t3.micro — some regions have
# dropped Graviton for the smallest RDS classes.

# 6. DOES THE DEPLOY ROLE EXIST, and do we really have iam:GetRole?
#    The account holder says yes; stock PowerUser says no. Find out now.
aws iam get-role --role-name sportable-lambda-api --query 'Role.Arn'
aws iam get-role --role-name sportable-github-deploy --query 'Role.Arn'

# 7. YOUR PUBLIC IP — the bastion security group will allow SSH from this only.
curl -s https://checkip.amazonaws.com
```

**Send me the output of all seven.** They determine the CIDR we can use, the
exact engine version, the AZ names in the subnet group, and whether we reference
the Lambda roles by data source or by variable.

## 0.2b Confirmed so far (29 Aug 2026)

| Check | Result |
|---|---|
| Account | `725699850301` — confirmed via the role ARNs below |
| `iam:GetRole` on the **user** | **Works.** The account holder granted more than stock PowerUser |
| `sportable-lambda-api` | `arn:aws:iam::725699850301:role/sportable-lambda-api` |
| `sportable-lambda-pipeline` | `arn:aws:iam::725699850301:role/sportable-lambda-pipeline` |
| `sportable-github-deploy` | `arn:aws:iam::725699850301:role/sportable-github-deploy` |
| RDS PostgreSQL versions | `16.9` – `16.15`; **16.4 removed** |
| Your public IP | `110.148.190.230` |

**Still outstanding:** availability zones (#2), what already exists in the
account (#3), and orderable instance classes (#5).

> **The public IP is residential and will change** — after a router reboot, or
> whenever your ISP decides. It goes into a `variable "allowed_ssh_cidrs"`, so
> reconnecting is a one-line edit and an apply, not a hunt through the console.
> Expect to do this at least once during the iteration.

> **GetRole works for your user, but the deploy role is a different principal.**
> The OIDC smoke test now probes it explicitly. If CI is denied, the Lambda role
> ARNs go in as variables rather than `data "aws_iam_role"` — otherwise
> `terraform plan` passes locally and fails in the pipeline.

## 0.3 Set the cost guard before creating anything

You are about to create the first resources that cost money. Do this first, not
after.

```bash
aws budgets create-budget --account-id 725699850301 --budget \
  '{"BudgetName":"sportable-guard","BudgetLimit":{"Amount":"20","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' \
  --notifications-with-subscribers \
  '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":50,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"charansaru8700@gmail.com"}]}]'
```

If this returns `AccessDenied`, the account holder's billing toggle has not
propagated to your user — tell him, it is a two-minute fix on his side.

---

# Part 1 — Primer: the concepts you are about to build

Skip nothing here. Every AWS mistake in this task comes from one of these five
ideas being fuzzy.

## 1.1 A VPC is a private network you rent

`10.0.0.0/16` is a **CIDR block** — an address range. The `/16` says the first
16 bits are fixed, leaving 16 bits for hosts: `10.0.0.0` through `10.0.255.255`,
about 65,000 addresses. We only need a few dozen; the size costs nothing and
leaves room.

We then carve it into **subnets**, each a smaller slice:

| Subnet | CIDR | Addresses | Holds |
|---|---|---|---|
| public | `10.0.0.0/24` | `10.0.0.0–10.0.0.255` | bastion |
| private A | `10.0.1.0/24` | `10.0.1.0–10.0.1.255` | Lambda ENI, RDS |
| private B | `10.0.2.0/24` | `10.0.2.0–10.0.2.255` | *(nothing)* |

AWS reserves five addresses in every subnet, so a `/24` gives you 251 usable.

## 1.2 "Public" and "private" are about routing, not a checkbox

There is no `public = true` flag. A subnet is public **only** because its route
table sends `0.0.0.0/0` (everywhere else) to an **Internet Gateway**.

```
public subnet route table            private subnet route table
  10.0.0.0/16  → local                 10.0.0.0/16  → local
  0.0.0.0/0    → igw-xxxx              (no default route at all)
```

The private subnets have **no default route**. Nothing in them can reach the
internet, and nothing on the internet can reach them. That is the entire
security model for the database — not a firewall rule that could be edited by
mistake, but the absence of a path.

## 1.3 Why the second private subnet is empty

RDS demands a **DB subnet group** covering at least two Availability Zones, even
for a single-AZ instance, so it can fail over if it ever needs to. Subnet B
exists purely to satisfy that constraint. It holds nothing and costs nothing.

Availability Zones are physically separate datacentres. `ap-southeast-2a` on
your account may be a different building from `ap-southeast-2a` on someone
else's — that is why check #2 above reports `ZoneId` as well as `ZoneName`.

## 1.4 Security groups are stateful allow-lists

A security group is a firewall attached to a network interface. Two properties
matter:

- **Allow-only.** There are no deny rules. If no rule permits traffic, it drops.
- **Stateful.** Allow a request in and the reply is automatically permitted. You
  never write a return rule.

The powerful part is that a rule's source can be **another security group**
rather than an IP range:

```
sportable-rds-sg
  ingress 5432/tcp  from  sportable-lambda-sg      ← not an IP, a group
  ingress 5432/tcp  from  sportable-bastion-sg
```

This says *"anything wearing the lambda badge may reach Postgres"*, regardless
of the address it happens to get today. Lambda ENIs come and go with random IPs;
an IP-based rule would be wrong within hours.

## 1.5 The S3 Gateway Endpoint — the single most important cost decision

A Lambda inside a private subnet has no internet route, so it cannot reach S3 by
the normal path. There are three ways to fix that:

| Option | How | Cost |
|---|---|---|
| NAT Gateway | routes private traffic out via a managed device | **~USD $45/month** + data |
| Interface endpoint | an ENI inside your subnet per service | ~USD $7/month each |
| **Gateway endpoint** | **a route-table entry to S3's prefix list** | **$0** |

A Gateway Endpoint is not a server. It is a line in a route table saying
"traffic destined for S3 goes over the AWS backbone." No hourly charge, no data
charge. It supports exactly two services — S3 and DynamoDB — and S3 is the one
we need.

**Never create a NAT Gateway on this project.** It would cost more per month
than everything else combined, and the endpoint makes it unnecessary.

## 1.6 Terraform state, and the chicken-and-egg

Terraform records what it created in a **state file**: a JSON map from your
`.tf` resources to real AWS ids. Without it, Terraform cannot tell "create a
VPC" from "you already have that VPC."

State must live in S3, not on your laptop, because the deploy pipeline needs to
read the same state you write. Two S3 features make that safe:

- **Versioning** — a corrupted state can be rolled back to yesterday's.
- **`use_lockfile = true`** — Terraform writes a small lock object beside the
  state, so two applies cannot run at once. This replaces the DynamoDB table you
  will see in every older tutorial; S3 gained conditional writes and HashiCorp
  has deprecated `dynamodb_table`.

**The chicken-and-egg:** the bucket that holds the state cannot itself be
managed by that state. So we create it once, by hand, with local state, and
never touch it again. That is Part 2.

---

# Part 2 — Bootstrap the state bucket (~30 min)

One-off. Local state, applied by you, committed for the record.

Bucket names are **globally unique across all AWS accounts**, so we suffix with
the account id.

```
infra/bootstrap/
  main.tf        the bucket, versioning, encryption, public access block
  versions.tf    provider constraints
  README.md      "applied once by hand on <date>; do not re-run in CI"
```

Then:

```bash
cd infra/bootstrap
terraform init          # local state, no backend block
terraform plan          # READ THIS. Expect ~5 resources, 0 to change, 0 to destroy
terraform apply
```

**`terraform plan` is not a formality.** Read every line of it, every time. It
is the only thing standing between a typo and a deleted database. The three
numbers that matter are on the last line: `Plan: X to add, Y to change, Z to
destroy`. If `destroy` is ever non-zero and you did not intend it, stop.

## What we will not do

We will **not** commit the bootstrap state file. It contains resource ids, and
state files can contain secrets in general. `.gitignore` already covers
`*.tfstate`.

---

# Part 3 — The network module (~4 h)

```
infra/modules/network/
  main.tf        VPC, subnets, IGW, route tables, associations, SGs, endpoint
  variables.tf   cidr, azs, name prefix, allowed SSH CIDR
  outputs.tf     vpc_id, subnet ids, sg ids — what database/ and api/ consume

infra/envs/staging/
  versions.tf    terraform >= 1.9, aws provider ~> 5.0
  providers.tf   region, default_tags
  backend.tf     the S3 backend from Part 2
  main.tf        module "network" { ... }
  variables.tf
  outputs.tf
```

## Why modules and environments are separate

A **module** is a reusable component that knows nothing about staging or prod.
An **environment** wires modules together with concrete values. The same network
module will build the prod VPC in Iteration 2 with different CIDRs and no code
change.

## Default tags — do this from the first line

```hcl
provider "aws" {
  region = "ap-southeast-2"
  default_tags {
    tags = {
      Project     = "sportable"
      Environment = "staging"
      ManagedBy   = "terraform"
      Owner       = "charan"
    }
  }
}
```

Every resource is tagged automatically. On a shared account this is what lets
you answer "which of these is mine?" — and lets you find everything at teardown.

## Build order inside the module

1. VPC
2. Internet Gateway, attached
3. Three subnets
4. Route tables + associations — **the association is a separate resource, and
   forgetting it is the most common VPC bug.** A subnet with no association
   silently uses the main route table
5. Security groups, with the SG-to-SG rules as **separate**
   `aws_vpc_security_group_ingress_rule` resources, not inline blocks
6. S3 Gateway Endpoint, associated with the private route table

> **Why separate rule resources.** Inline `ingress {}` blocks inside
> `aws_security_group` fight with rules created anywhere else: Terraform
> considers the inline list authoritative and deletes what it does not know
> about. The standalone resources compose properly and are what AWS's provider
> documentation now recommends.

## Verify before moving on

```bash
terraform output                       # ids for the next module
aws ec2 describe-route-tables --filters Name=vpc-id,Values=<vpc-id> \
  --query 'RouteTables[].[RouteTableId,Associations[].SubnetId,Routes[].[DestinationCidrBlock,GatewayId]]'
```

The private route table must show **no `0.0.0.0/0` entry** and one route to the
S3 prefix list. If a default route appears, the database is reachable from the
internet and the design has failed.

---

# Part 3b — What was actually built (29 Aug 2026)

`terraform apply` — **23 added, 0 changed, 0 destroyed**. Verified against the
live account, not just the apply output.

| Resource | Id |
|---|---|
| VPC `10.0.0.0/16` | `vpc-06c8668d6efe4ae91` |
| Public subnet `10.0.0.0/24` (2a) | `subnet-0c9e07927d0e2b38e` |
| Private subnet `10.0.1.0/24` (2a) | `subnet-0a17a1e1f6605dff3` |
| Private subnet `10.0.2.0/24` (2b) | `subnet-0cdfd397c78269135` |
| Internet Gateway | `igw-0d07ebc0542d2a187` |
| Public route table | `rtb-0b6d71307986276a5` |
| Private route table | `rtb-02ee0b648ce47d330` |
| S3 Gateway Endpoint | `vpce-0314d5ffda7b3d0d6` |
| bastion SG | `sg-0ac5adec5a5af769d` |
| lambda SG | `sg-079f8579bbd9e8fc9` |
| rds SG | `sg-0948bce8c871cab59` |
| default SG (adopted, stripped) | `sg-0a6bdb58f36e6f82a` |

## Verification evidence

```
private route table   10.0.0.0/16 → local
                      pl-6ca54005 → vpce-0314d5ffda7b3d0d6
                      NO 0.0.0.0/0 route          ← the design holds

public route table    10.0.0.0/16 → local
                      0.0.0.0/0   → igw-0d07ebc0542d2a187

default SG            0 ingress rules, 0 egress rules
rds SG                5432/tcp from lambda SG and bastion SG only; no CIDR anywhere
S3 endpoint           Gateway, available, attached to the private route table
subnets               2a public, 2a private, 2b private; MapPublicIpOnLaunch false on all
```

## Running cost so far: USD $0.00/month

VPCs, subnets, Internet Gateways, route tables, security groups and **Gateway**
endpoints are all free. Nothing created so far accrues a cent. Cost begins with
the RDS instance in Part 4.

Re-run this any time to confirm the private subnets are still sealed:

```bash
aws ec2 describe-route-tables --route-table-ids rtb-02ee0b648ce47d330 \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock,GatewayId]' --output table
```

---

# Part 4 — RDS PostgreSQL with PostGIS (~4 h)

The part where people get stuck, so read this before writing it.

## What Terraform creates

- `aws_db_subnet_group` across private A and private B
- `aws_db_parameter_group` — PostgreSQL 16 family
- `aws_db_instance` — `db.t4g.micro`, 20 GB gp3, `publicly_accessible = false`,
  `storage_encrypted = true`, `skip_final_snapshot = true` for staging,
  `engine_version = "16.10"`, `auto_minor_version_upgrade = false`

> **Why 16.10, and why pinned.** Checked on this account 29 Aug 2026: RDS offers
> **16.9 – 16.15**; 16.4 has already been removed. 16.10 is chosen because the
> local container image `imresamu/postgis:16-3.5` ships exactly PostgreSQL
> 16.10, so local and staging run the same engine. Minor upgrades are disabled
> for the iteration so the demo environment cannot change during assessment
> week — re-enable them afterwards.
>
> **Do not switch the team's local image yet.** The PostGIS version matters more
> than the Postgres minor for spatial SQL, and we only learn which PostGIS RDS
> gives us once the instance exists:
>
> ```sql
> SELECT * FROM pg_available_extensions WHERE name = 'postgis';
> ```
>
> Read that first, then pin the local tag to match — one change, announced once,
> instead of churning five people twice.
- `random_password` → `aws_ssm_parameter` as a **SecureString**

## The credential rule

The password is generated by Terraform and written straight into SSM Parameter
Store. It is **never** a Terraform output, never in the repo, never a GitHub
secret. The API reads it from SSM at cold start; you read it from SSM when you
need to connect.

```bash
aws ssm get-parameter --name /sportable/staging/db/url --with-decryption \
  --query 'Parameter.Value' --output text
```

> It will still appear in the Terraform **state file**. That is unavoidable with
> `random_password`, and it is why the state bucket is encrypted and private.

## PostGIS is not automatic

RDS ships the extension but does not enable it. After the instance is up,
connect through the bastion and run:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT postgis_version();
```

On RDS the master user is **not** a superuser — it holds `rds_superuser`, which
is permitted to create PostGIS. If you hit a permissions error, you are
connected as the wrong role.

This belongs in the **first Alembic migration**, not in a one-off psql session,
so a rebuilt database gets it automatically.

## Cost, and how to not pay it

| | ~USD/month if left running |
|---|---:|
| `db.t4g.micro` + 20 GB gp3 | ~17 |
| bastion `t3.micro` + its public IPv4 | ~13 |
| **total** | **~30** |

Estimates — verify in the AWS Pricing Calculator. Against $120 of credits over
the ~9 remaining weeks that is comfortable, but only if you stop things:

```bash
aws rds stop-db-instance --db-instance-identifier sportable-db     # storage only, ~$2/mo
aws ec2 stop-instances --instance-ids <bastion-id>

aws rds start-db-instance --db-instance-identifier sportable-db
aws ec2 start-instances --instance-ids <bastion-id>
```

A stopped RDS instance restarts itself after 7 days. Stop it again; that is
normal and expected.

---

# Part 5 — Bastion and the SSH tunnel (~2 h)

The database has no public address by design. The bastion is a small EC2
instance in the public subnet that you SSH into, forwarding a local port through
it to RDS.

```bash
ssh -i ~/.ssh/sportable.pem -L 5433:<rds-endpoint>:5432 ec2-user@<bastion-ip>
```

Then, in another terminal, `localhost:5433` **is** the RDS database — the same
port your local container uses, so `DATABASE_URL` is identical either way.

> Stop the local Docker container first, or the port is taken.

Security group: SSH from **your team's IPs only**, never `0.0.0.0/0`. Home IPs
change; when someone is locked out, update the rule rather than widening it.

## What to hand the Data team

Once this works, they get the tunnel command and the SSM parameter name. They do
not need AWS console access, and they do not need to understand any of the above.

---

# The AWS Free plan restricts capabilities, not just spend

Account `7256-9985-0301` is on the AWS Free plan (the $120-credit model). That
plan blocks certain *features and resource types outright*, regardless of
whether you are willing to pay. Three were hit while building T1, each only
discovered at apply time:

| What failed | Error | Fix |
|---|---|---|
| RDS backup retention of 7 days | `FreeTierRestrictionError: The specified backup retention period exceeds the maximum available to free tier customers` | Reduced to 1 day |
| Bastion on `t4g.nano` | `InvalidParameterCombination: The specified instance type is not eligible for Free Tier` | Changed to `t4g.micro` |
| Resource Group description containing `;` and `/` | `Member must satisfy regular expression pattern: [\sa-zA-Z0-9_\.-]*` | *(not a Free plan issue — a Resource Groups charset rule)* |

**How to recognise one:** the error says `FreeTierRestrictionError`, or mentions
Free Tier eligibility. It is the plan refusing, not a mistake in the Terraform.

**Discover what is permitted before writing the resource**, rather than after:

```bash
# Which EC2 instance types may run at all
aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true \
  --query 'InstanceTypes[].[InstanceType,ProcessorInfo.SupportedArchitectures[0]]' --output table

# Which RDS classes are orderable for a given engine version
aws rds describe-orderable-db-instance-options --engine postgres \
  --engine-version 16.10 --db-instance-class db.t4g.micro \
  --query 'OrderableDBInstanceOptions[].StorageType' --output text
```

Eligible EC2 types on this account, 29 Aug 2026: `t4g.micro`, `t4g.small`,
`t3.micro`, `t3.small`, `c7i-flex.large`, `m7i-flex.large`.

**Expect more of these** in T2 and T4. When something fails at apply with no
obvious cause, check the plan restriction before debugging the configuration.

---

# Definition of done

- [ ] `terraform apply` completes with no errors, from a clean `plan`
- [ ] Private route table has **no** `0.0.0.0/0` route
- [ ] `aws rds describe-db-instances` shows `PubliclyAccessible: false`
- [ ] `SELECT postgis_version()` answers through the bastion tunnel
- [ ] The password exists only in SSM — `grep -ri "password" infra/` finds nothing
- [ ] One Data team member has connected successfully
- [ ] The budget alarm exists and you have had the test email
- [ ] `terraform destroy` on a scratch copy proves teardown works

---

# If it goes wrong

| Symptom | Cause |
|---|---|
| `apply` hangs ~20 min then fails on RDS | Normal creation time is 8–12 min; longer means a subnet group or parameter group problem |
| Cannot connect through the tunnel | Check the RDS SG allows 5432 **from the bastion SG**, not from an IP |
| `CREATE EXTENSION postgis` → permission denied | Connected as the wrong user; use the master user from SSM |
| `InvalidParameterValue: DBSubnetGroup` | Subnets are in the same AZ — it needs two |
| Terraform says it will destroy the database | **Stop.** Almost always a changed `identifier` or `az`. Read the plan and ask |

**Never** run `terraform apply` when the plan shows a destroy you did not
intend, and never use `-auto-approve` from your laptop. That flag belongs only
in the pipeline, where the plan has already been reviewed.

---

# What I need from you before we start

1. Output of the **seven pre-flight commands** in Part 0.2
2. Confirmation the **budget** was created (or the AccessDenied text)
3. Your **public IP** from check #7, for the bastion security group

With those I will write the bootstrap and the network module, you review the
plan, and you run the apply.

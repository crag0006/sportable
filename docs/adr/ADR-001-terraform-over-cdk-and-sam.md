# ADR-001 — Terraform, not AWS CDK or SAM

| | |
|---|---|
| **Status** | Accepted |
| **Date decided** | 24 August 2026 |
| **Date recorded** | 1 September 2026 |
| **Decider** | Charan — Infrastructure / Platform |
| **Affects** | Everything under `infra/`, and how anyone changes the system |

---

## Context

SportAble needs a VPC, a PostGIS database, Lambda functions, an HTTP API, a
CDN, object storage and a deployment pipeline — built by **one engineer** in a
nine-week student project, on a **shared AWS account** owned by a teammate.

Two constraints shaped the choice more than any technical preference:

- **The account is not ours.** Access is an IAM user carrying `PowerUserAccess`.
- **The role is a learning role.** Platform engineering is the part of this
  project I am meant to come out understanding, not just the part I am meant to
  finish.

## Options considered

| Option | What it is |
|---|---|
| **AWS CDK** | Write TypeScript or Python; it synthesises CloudFormation and deploys it |
| **AWS SAM** | A CloudFormation dialect specialised for serverless applications |
| **Terraform** | A declarative language (HCL) with its own state and plan/apply cycle |
| ~~The console~~ | Rejected without discussion. Clicking is not reproducible, not reviewable, and not deletable |

## Decision

**Terraform.**

### Why

**1. The plan is a first-class artifact, and it is our main safety net.**

`terraform plan` prints exactly what will change, before anything changes, and
ends with a line a human can act on:

```
Plan: 9 to add, 0 to change, 0 to destroy.
```

Our whole review discipline rests on reading that line. It caught two
unintended destroys in a single day — a bastion that a stopped instance made
Terraform want to replace, and a CloudFront origin that a trailing slash would
have broken. CloudFormation change sets exist and `cdk diff` exists, but neither
is as central to the daily loop, and neither is as easy to make someone read.

**2. State we can reach into.**

Terraform's state is a file in our own versioned S3 bucket. When something goes
wrong we can inspect it, move a resource, or import one.

CloudFormation's state lives inside CloudFormation. A stack that reaches
`UPDATE_ROLLBACK_FAILED` is a support-ticket conversation, not a command. On a
project with a fixed deadline and no AWS support plan, that risk is not
theoretical.

**3. Pre-deploy checking that actually catches things.**

`tflint` with the AWS ruleset validates against real AWS constraints before
anything is submitted — it is what catches `db.t4g.mikro` as a typo rather than
a fifteen-minute failed deploy. `checkov` reads HCL natively and found a real
security problem nobody had thought about (the default security group).

CloudFormation has `cfn-lint` and checkov supports it, but with CDK the thing
under review is the *generated* template, which is not the thing anyone wrote.

**4. It is the more transferable skill.**

Terraform is used across employers and across clouds. CDK is AWS-only, and SAM
is AWS-and-serverless-only. Given the learning goal, that mattered.

### The reason that would have decided it anyway

Discovered later, during T1, and worth recording because it is decisive rather
than a preference:

**CDK cannot be bootstrapped on this account.**

`cdk bootstrap` creates roughly five IAM roles — deploy, file-publishing,
image-publishing, lookup and cfn-exec — plus an S3 bucket and an ECR repository.
The available principal carries `PowerUserAccess`, whose policy is
`NotAction: ["iam:*", ...]`. **Every IAM write is denied.**

That was confirmed repeatedly and not by guessing:

```
iam:UpdateAssumeRolePolicy      AccessDenied
iam:ListAttachedRolePolicies    AccessDenied
iam:SimulatePrincipalPolicy     AccessDenied
```

It is also why both Lambda execution roles had to be pre-built by the account
holder and hardcoded as ARNs in `variables.tf` rather than created or even
inspected by our code.

Terraform needs no bootstrap of its own beyond an S3 bucket, which
`PowerUserAccess` permits. Had we chosen CDK, the project would have stopped on
day one waiting on a teammate with administrator access.

## Consequences

### Accepted costs

- **We manage state ourselves.** One bucket, created by hand, once, with local
  state — a pipeline cannot create the thing it needs in order to run. That is
  `infra/bootstrap/`, and it is deliberately the only thing ever applied
  manually.
- **HCL is another language to learn**, and it has no type checking of resource
  properties at authoring time. CDK in TypeScript would have caught some
  mistakes in an editor that we instead catch in `terraform validate`.
- **More code.** CDK's L2 constructs would have produced a CloudFront
  distribution with Origin Access Control in a handful of lines; ours is 336
  lines of HCL with comments. We consider the comments an asset, but the
  verbosity is real.
- **Locking.** Solved with `use_lockfile = true` on the S3 backend rather than
  the DynamoDB table every older tutorial shows. DynamoDB never stored state —
  it was only a mutex, because S3 once could not do a conditional write. It can
  now, and HashiCorp has marked `dynamodb_table` deprecated.

### What we gained

- A change is reviewable as a diff *and* as a plan, before it happens.
- The same four checks run on infrastructure as on application code.
- Nothing about the system exists only in someone's console history.

## Revisit when

The team moves to an account where IAM is available **and** the majority of new
work is Lambda-only. SAM's local invocation and testing story is genuinely
better for that shape of application, and would be worth re-examining.

Not before Iteration 2, and not while the account constraint stands.

## See also

- [ADR-002](ADR-002-gateway-endpoint-over-nat.md) — the cost decision that shaped the network
- `infra/bootstrap/main.tf` — the one thing applied by hand
- `infra/README.md` — how to run the plan/apply loop

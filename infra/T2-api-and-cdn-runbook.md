# T2 — Public HTTPS Site and API: Runbook and Primer

**SportAble Melbourne** · FIT5120 · Iteration 1 · Infra/Platform owner: Charan

| | |
|---|---|
| **Task** | T2 — *Put the site and its API on a public HTTPS address* (8.5 h) |
| **Serves** | US1.1 · AC1.1.1, AC1.1.2, AC1.1.5 — search for venues as soon as the site opens |
| **Also serves** | The shared Definition of Done — *"demonstrated from that URL rather than from a laptop"* |
| **Account** | `7256-9985-0301`, region `ap-southeast-2` |
| **Written** | 29 Aug 2026 · Iteration 1 closes Sun 6 Sep |

---

## Why this task now

T1 built a database nobody outside the VPC can reach. That is correct, and it
also means **nothing is currently demonstrable**. The Definition of Done is not
"the infrastructure exists" — it is "demonstrated from that URL".

T2 produces the URL. Until it exists, Iteration 1 cannot be marked.

The order inside T2 matters for the same reason: **the static site comes first**,
because an S3 bucket behind CloudFront serving a placeholder page already
satisfies "there is a live HTTPS URL". Everything after that improves it.

---

# Part 0 — Preparation

## 0.1 Confirm you are on the right account

```bash
export AWS_PROFILE=sportable
aws sts get-caller-identity --query Account --output text     # must be 725699850301
```

## 0.2 Pre-flight checks

The Free plan blocks capabilities, not just spend — three restrictions bit us in
T1, each only at apply time. Check before writing, not after.

```bash
# 1. Can this account use CloudFront at all, and is anything already there?
aws cloudfront list-distributions --query 'DistributionList.Quantity'

# 2. Any existing Lambda functions to avoid colliding with?
aws lambda list-functions --query 'Functions[].FunctionName'

# 3. THE IMPORTANT ONE — what can the pre-built Lambda role actually do?
#    We cannot create IAM roles on this account, so we must use the role the
#    account holder made. If it lacks VPC networking permissions, a Lambda
#    inside the VPC will fail to initialise.
aws iam get-role --role-name sportable-lambda-api \
  --query 'Role.AssumeRolePolicyDocument'
aws iam list-attached-role-policies --role-name sportable-lambda-api
aws iam list-role-policies --role-name sportable-lambda-api

# 4. Existing API Gateway APIs
aws apigatewayv2 get-apis --query 'Items[].[ApiId,Name,ProtocolType]' --output table
```

**Check 3 is the one that can derail this task.** See §1.6.

---

## 0.3 Pre-flight results (29 Aug 2026)

| Check | Result |
|---|---|
| CloudFront | Usable. **No existing distributions** |
| Lambda | **No existing functions** |
| API Gateway | **No existing APIs** |
| `sportable-lambda-api` trust policy | Correct — `lambda.amazonaws.com` may assume it |
| `sportable-lambda-api` permissions | ❓ **Cannot be determined** |

**We cannot see what the Lambda role is allowed to do.** Both
`iam:ListAttachedRolePolicies` and `iam:ListRolePolicies` are denied on this
user, so §1.6's question — does the role carry
`AWSLambdaVPCAccessExecutionRole`? — is unanswerable from here.

**That is acceptable, because Lambda answers it for us.** `CreateFunction` with
a `VpcConfig` validates the role's networking permissions at creation time and
fails immediately and legibly:

```
InvalidParameterValueException: The provided execution role does not have
permissions to call CreateNetworkInterface on EC2
```

So Step 2 is the test. It costs seconds, not a round trip. Ask the account
holder in parallel so the answer arrives before it is needed, rather than
waiting on it now.

## 0.4 Decisions taken

| Question | Decision | Consequence |
|---|---|---|
| Custom domain | **None for Iteration 1** | No ACM, no Route 53. CloudFront's own `*.cloudfront.net` certificate. **TLS minimum cannot be raised above TLSv1** with the default certificate — a real limitation, documented rather than hidden |
| Lambda → SSM | **Environment variable** | Terraform reads SSM and passes the value. No interface endpoints (~$14/month saved). The secret then exists in the Lambda configuration and in Terraform state. Recorded as a known compromise for T6; revisit in Iteration 2 |

# Part 1 — Primer: the concepts

## 1.1 The shape of what we are building

```
browser
  │  HTTPS
  ▼
CloudFront distribution           ← one public origin, one certificate
  ├── default behaviour  ──────►  S3 bucket (private, OAC)      the SPA
  └── /api/*             ──────►  API Gateway HTTP API           the API
                                       │
                                       ▼
                                  Lambda (in the VPC)
                                       │  5432
                                       ▼
                                  RDS PostGIS  ← built in T1
```

**Everything comes through CloudFront.** That is a deliberate choice with a
large consequence: because the SPA and the API share one origin, **the browser
never makes a cross-origin request, so CORS does not apply at all.** No
preflight, no `Access-Control-Allow-Origin` headers, no class of bug that eats
an afternoon.

The alternative — SPA on CloudFront calling API Gateway directly — needs CORS
configured correctly on every route and is the more common source of "it works
in Postman but not the browser".

## 1.2 S3 with Origin Access Control, not a public bucket

There are three ways to serve a site from S3, and two are wrong here.

| Approach | Verdict |
|---|---|
| Public bucket + S3 website endpoint | ✗ Bucket must be world-readable. **HTTP only** — no TLS |
| CloudFront + Origin Access Identity (OAI) | ✗ The legacy mechanism, superseded |
| **CloudFront + Origin Access Control (OAC)** | ✓ Bucket stays fully private |

With OAC, the bucket blocks all public access and its policy grants read **only
to this specific CloudFront distribution**, matched by ARN. Fetching the S3 URL
directly returns 403. The only route in is CloudFront, which means TLS is not
optional and cannot be bypassed.

`checkov` will still complain the bucket has no public-access block if you
forget one — leave the block on. OAC works with it.

## 1.3 The SPA fallback, and why a 403 becomes a 200

A single-page app has one real file, `index.html`. Routes such as
`/venues/melbourne-sports-centre` exist only in JavaScript. Ask S3 for that key
and there is no such object.

With OAC the bucket does not grant `s3:ListBucket`, so a missing object returns
**403, not 404** — a detail that surprises people.

So CloudFront is configured to turn both into the app:

```
403 → /index.html, response code 200
404 → /index.html, response code 200
```

The `200` matters. Returning the app with a 403 status makes the browser treat
a perfectly good page as an error, and search engines drop it.

> **Do not apply this to `/api/*`.** A genuine 404 from the API must stay a 404,
> or the frontend receives HTML where it expected JSON. Error responses are
> distribution-wide in CloudFront, so the API behaviour must be separated by
> path — which is why `/api/*` gets its own behaviour with its own settings.

## 1.4 Caching: the one rule that will bite you

CloudFront caches by default. That is the point for the SPA bundle, and a
disaster for the API — a stale venue search served for 24 hours, invisible in
logs because the request never reaches Lambda.

| Behaviour | Cache policy | Why |
|---|---|---|
| default (SPA) | `CachingOptimized` (managed) | Hashed asset filenames; long TTLs are safe |
| `/api/*` | **`CachingDisabled`** (managed) | Every request must reach the API |

`index.html` itself is the exception inside the SPA: it must **not** be cached
long, or users keep loading an old app that references deleted asset files. The
deploy pipeline's CloudFront invalidation handles this in T3.

**One more `/api/*` requirement that is easy to miss.** Attach the managed
origin request policy **`AllViewerExceptHostHeader`**. CloudFront otherwise
forwards the viewer's `Host` header, and API Gateway rejects a request whose
Host does not match its own domain — producing a confusing 403 that looks like
an authorisation problem.

## 1.5 API Gateway: HTTP API, not REST API

AWS has two. The names are unhelpful; both do HTTP.

| | HTTP API | REST API |
|---|---|---|
| Price per million requests | ~$1.00 | ~$3.50 |
| Latency | Lower | Higher |
| Features | Routes, JWT auth, CORS | Request validation, API keys, WAF, usage plans |

We need none of the REST-only features. HTTP API is cheaper, faster and
simpler. This is `aws_apigatewayv2_*` in Terraform, not `aws_api_gateway_*` —
the resource names are an ongoing source of copy-paste errors.

## 1.6 The Lambda execution role — the constraint that shapes this task

Every Lambda needs an execution role. **We cannot create IAM roles on this
account**, so we must use `sportable-lambda-api`, pre-built by the account
holder, on which we hold `iam:PassRole`.

A Lambda that runs **inside a VPC** requires its role to allow:

```
ec2:CreateNetworkInterface
ec2:DescribeNetworkInterfaces
ec2:DeleteNetworkInterface
```

These are exactly the AWS-managed policy `AWSLambdaVPCAccessExecutionRole`.
Lambda uses them to attach an elastic network interface into your subnet.

**If that role lacks them, the function is created successfully and then fails
at first invocation** with an unhelpful error about being unable to configure
the VPC. It is not a Terraform problem and no amount of re-applying fixes it.

Check 3 in §0.2 answers this before you write a line. If the policy is missing,
ask the account holder to attach:

```
arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole
```

The role will also need, for the real API later:
- `ssm:GetParameter` + `kms:Decrypt` on `/sportable/staging/*` — to read the DB URL
- `logs:CreateLogStream`, `logs:PutLogEvents` — via `AWSLambdaBasicExecutionRole`

**Ask for all three in one message.** Each round trip with him has cost hours.

## 1.7 Why the Lambda goes in the VPC at all

Only because it must reach RDS, which has no public address. That has costs:

- **Cold starts are longer** — an ENI must be attached
- **No internet access** — the private subnets have no default route. Anything
  the function needs from the public internet is unreachable. This is why T4's
  *fetch* Lambda lives **outside** the VPC
- It consumes IP addresses in the subnet

For Iteration 1 the API only talks to RDS and SSM, so this is fine. SSM is
reached through... nothing yet — see the open question in §4.

## 1.8 No custom domain, and therefore no ACM

The original task sketch mentioned an ACM certificate. **Skip it**, for two
reasons:

1. **No domain is registered for this project.** ACM issues certificates for
   domains you control and validates via DNS or email. Without a domain there is
   nothing to certify.
2. **CloudFront certificates must live in `us-east-1`**, regardless of where
   everything else runs — a genuine cross-region requirement that surprises
   people. Not worth setting up for a domain you do not have.

CloudFront gives every distribution a working HTTPS name for free:

```
https://d1234abcd.cloudfront.net
```

That satisfies "a public HTTPS address". If the team buys a domain later, adding
ACM plus an alias is a contained change — roughly an hour — and belongs in
Iteration 2.

> If someone already owns a suitable domain, say so now rather than in week
> three: it changes T2's scope and needs DNS access.

## 1.9 Lambda versions and aliases — build this now, use it in T3

`deploy-staging.yml` will publish a new Lambda version, shift an alias, run a
smoke test, and **move the alias back if the test fails**. That rollback only
works if the alias exists from the start.

- A **version** is an immutable snapshot of code and configuration
- An **alias** is a named pointer to a version (`live` → version 7)
- API Gateway integrates with the **alias**, never with `$LATEST`

Get this right in T2 and T3's rollback is three lines. Get it wrong and there is
nothing to roll back to.

---

# Part 2 — Build order

Each step leaves something demonstrable. Do not reorder.

### Step 1 — `modules/static_site` (~3 h)

S3 bucket (private, versioned, encrypted, public access blocked) · CloudFront
distribution with OAC · SPA fallback · `CachingOptimized` default behaviour ·
bucket policy scoped to the distribution ARN.

Upload a placeholder `index.html` by hand.

**Done when:** the CloudFront URL serves a page over HTTPS, and the S3 URL
returns 403.

**At this point the Definition of Done is no longer at risk.**

### Step 2 — `modules/api`, Lambda first (~2 h)

Package `backend/handlers/stub.py` with `archive_file` · Lambda (Python 3.12,
512 MB, 10 s) using the pre-built role · VPC config with T1's lambda security
group and private subnet · a published version and a `live` alias.

**Done when:** `aws lambda invoke --function-name sportable-staging-api:live`
returns `{"status":"ok"}`.

### Step 3 — API Gateway in front of it (~1.5 h)

HTTP API · `$default` stage with auto-deploy · integration to the alias ·
`lambda:InvokeFunction` permission for API Gateway (a **resource policy**, not
IAM — permitted under PowerUser) · access logging to CloudWatch with 14-day
retention · throttling.

**Done when:** the API Gateway invoke URL returns the stub payload.

### Step 4 — join them (~1 h)

Add an `/api/*` behaviour to the distribution with API Gateway as origin,
`CachingDisabled`, and `AllViewerExceptHostHeader`.

**Done when:** `https://<distribution>/api/v1/health` returns 200 **and**
`https://<distribution>/` still serves the page.

### Step 5 — mock responses for the Frontend team (~1 h)

Routes for `/venues/search`, `/venues/{id}` and `/sports` returning the OpenAPI
contract's example payloads. Real URL, real status codes, fixture bodies.

**This unblocks both Frontend engineers before a single endpoint exists.** Tell
them the same day.

---

# Part 3 — Cost

| | |
|---|---|
| CloudFront | 1 TB egress + 10M requests/month always free. This project will not approach it |
| S3 | A few MB of bundle. Pennies |
| API Gateway HTTP API | ~$1.00 per million requests |
| Lambda | 1M requests + 400,000 GB-seconds/month always free |
| **Realistic T2 total** | **~$0/month** |

Unlike T1, nothing here runs when idle. There is nothing to stop at night.

> Set CloudFront's `price_class` to **`PriceClass_All`**. The cheaper classes
> exclude Oceania, which would route Melbourne users via Singapore or the US —
> a strange choice for an application about Melbourne venues.

---

# Definition of done

- [ ] CloudFront URL serves the placeholder over HTTPS
- [ ] The S3 bucket URL returns 403 — the only way in is CloudFront
- [ ] A deep link such as `/venues/anything` returns the app with **status 200**
- [ ] `/api/v1/health` returns 200 through the CloudFront domain
- [ ] `/api/*` responses carry no cache headers; the SPA bundle does
- [ ] The Lambda has a published version and a `live` alias
- [ ] API Gateway integrates with the **alias**, not `$LATEST`
- [ ] Mock routes serve the contract's examples, and Frontend has been told
- [ ] `terraform plan` is clean; `checkov` passes with documented skips only

---

# Failure modes to expect

| Symptom | Cause |
|---|---|
| CloudFront returns 403 for everything | Bucket policy does not match the distribution ARN, or OAC is not attached to the origin |
| Deep links 404 | Custom error responses missing, or applied to the wrong behaviour |
| API returns 403 through CloudFront but works directly | The `Host` header is being forwarded — use `AllViewerExceptHostHeader` |
| API responses are stale | `/api/*` is using the default cache policy instead of `CachingDisabled` |
| Lambda times out on first invocation | Execution role lacks `AWSLambdaVPCAccessExecutionRole` — see §1.6 |
| Lambda cannot read SSM | Role lacks `ssm:GetParameter`/`kms:Decrypt`, **or** there is no route to the SSM endpoint |
| Changes to the distribution take 5+ minutes | Normal. CloudFront propagates globally |

---

# Open question to settle before Step 2

**How does the in-VPC Lambda reach SSM Parameter Store?**

The private subnets have no internet route — deliberately. S3 is reachable
through the Gateway Endpoint built in T1, but **SSM is not S3**, and a Gateway
Endpoint only supports S3 and DynamoDB.

Three options:

| Option | Cost | Notes |
|---|---|---|
| Interface VPC endpoints for `ssm` and `kms` | ~USD $14/month | Correct, and the pattern used in production |
| Pass the DB URL as a Lambda **environment variable** | $0 | Terraform reads SSM and sets the variable. The secret then sits in the Lambda configuration and in Terraform state |
| Move the API Lambda **outside** the VPC | $0 | Then it cannot reach RDS at all. Not viable |

For Iteration 1 with a stub handler this does not arise — the stub reads
nothing. **It must be decided before the real handler lands**, and the honest
trade is $14/month against a secret in an environment variable.

My recommendation: **environment variable for Iteration 1**, documented as a
known compromise in T6, with interface endpoints in Iteration 2 when the cost is
justified. Discuss before implementing.

---

# What I need from you before Step 1

1. Output of the four pre-flight commands in §0.2 — especially check 3
2. Confirmation that **no custom domain** exists for this project (§1.8)
3. Your call on the SSM question above, or agreement to defer it to Step 2

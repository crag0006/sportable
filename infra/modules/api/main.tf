# ==============================================================================
# api — Lambda behind an alias, ready for API Gateway
# ==============================================================================
#
# WHAT THIS STEP BUILDS
#   The compute half of T2: a Python Lambda inside the VPC, with a published
#   version and a `live` alias. API Gateway is added on top in the next step.
#
# WHY AN ALIAS FROM DAY ONE
#   T3's deploy pipeline publishes a new version, shifts the alias, runs a smoke
#   test, and moves the alias BACK if the test fails. That rollback only exists
#   if the alias does. Wire it now and the pipeline is three lines; leave it out
#   and there is nothing to roll back to.
#
#     version  — an immutable snapshot of code and configuration
#     alias    — a named pointer to a version (live -> 7)
#     $LATEST  — the mutable working copy. API Gateway must NEVER point here
#
# WHY THIS LAMBDA IS INSIDE THE VPC
#   Only because it must reach RDS, which has no public address. The cost is a
#   longer cold start (an ENI must be attached) and NO INTERNET ACCESS — the
#   private subnets have no default route. That is why T4's fetch Lambda, which
#   downloads from open-data portals, will live outside the VPC instead.
# ==============================================================================

# ------------------------------------------------------------------- packaging
# Zips the handler directory at plan time. Files land at the ROOT of the
# archive, so backend/handlers/stub.py becomes stub.py — which is why the
# handler is "stub.handler" and not "handlers.stub.handler".
#
# This is fine for a stub with no dependencies. The real handler needs FastAPI,
# Mangum and psycopg, which do not belong in a Terraform-built zip: T3's
# pipeline will build the package with uv and upload it, and this becomes the
# fallback for a bare deploy.
# The deployment package is BUILT, not just zipped.
#
# The stub handler needed no dependencies, so zipping backend/handlers/ was
# enough. The real application imports FastAPI, Pydantic, SQLAlchemy, psycopg
# and Mangum — none of which are in the Lambda runtime — so something has to
# install them first, for the RIGHT platform.
#
# `archive_file` cannot do that. It zips a directory; it cannot run pip. So
# backend/scripts/build_lambda.sh installs the locked dependencies for
# x86_64-manylinux_2_28 (Lambda's python3.12 runs on Amazon Linux 2023) into
# backend/build/package/, and this data source zips the result.
#
#   bash backend/scripts/build_lambda.sh     # ~30 MB zipped, ~81 MB unpacked
#
# The pipeline runs that before `terraform plan`. If you are applying by hand,
# you must run it too — hence the precondition below, which fails with an
# instruction rather than silently deploying whatever was last built.
data "archive_file" "package" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${var.name_prefix}-api.zip"

  lifecycle {
    precondition {
      # The entrypoint module. Its absence means the build has not been run, and
      # zipping an empty or stale directory would deploy a function that fails
      # at import with no useful message.
      condition     = fileexists("${var.source_dir}/${replace(var.handler, ".handler", "")}.py")
      error_message = "Deployment package not built. Run:  bash backend/scripts/build_lambda.sh"
    }
  }
}

# --------------------------------------------------------------------- logging
# Created BEFORE the function. If Lambda creates its own log group, retention is
# "never expire" — which silently consumes the 5 GB CloudWatch free allowance
# and then bills forever. Creating it first means our retention wins.
resource "aws_cloudwatch_log_group" "api" {
  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems. This is a nine-week student staging
  #   environment; 12 months would outlive the project while consuming the 5 GB
  #   CloudWatch free allowance.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month to
  #   encrypt application logs that are already encrypted at rest with the
  #   CloudWatch service key.
  name              = "/aws/lambda/${var.name_prefix}-api"
  retention_in_days = var.log_retention_days

  tags = { Name = "${var.name_prefix}-api-logs" }
}

# ------------------------------------------------------------- the DB URL
# Read at plan time and passed as an environment variable. See the variable's
# documentation for why this is not read at runtime.
data "aws_ssm_parameter" "db_url" {
  name = var.db_url_ssm_parameter
}

# ------------------------------------------------------------------------------
# Search configuration, read at APPLY time — not at runtime
# ------------------------------------------------------------------------------
#
# The obvious design is for the handler to call Parameter Store itself at cold
# start. It was built that way first, and it timed out in production.
#
# WHY. This function runs in a private subnet whose route table holds exactly
# two entries: `local`, and the S3 gateway endpoint. There is no route to
# ssm.ap-southeast-2.amazonaws.com. The SDK call did not fail — it HUNG, until
# the 10 s function timeout killed the whole invocation and API Gateway returned
# a 500. A try/except around it caught nothing, because a hang is not an
# exception.
#
# Reaching SSM from inside the VPC needs an INTERFACE endpoint, which is roughly
# USD $7.30/month per availability zone. That is more than this project's entire
# monthly budget target, to save one minute on a config change.
#
# So the read happens HERE instead, on the CI runner, which has ordinary
# internet access — exactly how DATABASE_URL above already works. Terraform
# fetches the live values and bakes them into the function's environment.
#
# WHAT THIS COSTS. Changing a band is no longer live; it takes a pipeline run,
# about a minute. What it is NOT is a code change: the parameters carry
# ignore_changes on their value, so `aws ssm put-parameter` followed by
# `gh workflow run deploy-staging.yml` is the whole procedure. No PR, no review,
# no edit to a Python file. That was the point of T5, and it survives.
data "aws_ssm_parameters_by_path" "search" {
  path = "${var.ssm_prefix}/search"
}

# -------------------------------------------------------------------- function
resource "aws_lambda_function" "api" {
  # checkov:skip=CKV_AWS_115:Reserved concurrency cannot be set on this account
  #   — its total Lambda concurrency limit is 10, and AWS will not allow the
  #   unreserved pool to fall below that. The account-wide limit gives the same
  #   protection. See the reserved_concurrency variable.
  # checkov:skip=CKV_AWS_50:X-Ray tracing needs xray:PutTraceSegments on the
  #   execution role. That role is pre-built by the account holder and we cannot
  #   read or change its policies, so enabling tracing would fail at runtime
  #   rather than at apply. Revisit once tracing permissions are confirmed.
  # checkov:skip=CKV_AWS_116:A dead letter queue only applies to ASYNCHRONOUS
  #   invocations. API Gateway invokes synchronously, so a failure is returned
  #   to the caller as a 5xx — there is nothing for a DLQ to catch.
  # checkov:skip=CKV_AWS_173:Environment variables are encrypted at rest with
  #   the AWS-managed Lambda key. A customer managed key adds ~USD $1/month and
  #   does not change who can read the configuration.
  # checkov:skip=CKV_AWS_272:Code signing requires an AWS Signer profile and a
  #   signing step in the pipeline. Disproportionate for a nine-week project
  #   whose only publisher is a branch-scoped OIDC role.
  function_name = "${var.name_prefix}-api"
  description   = "SportAble API. Stub handler until the FastAPI application lands."

  role    = var.execution_role_arn
  handler = var.handler
  runtime = var.runtime

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  memory_size = var.memory_mb
  timeout     = var.timeout_seconds

  reserved_concurrent_executions = var.reserved_concurrency

  # publish = true creates an immutable version on every code change, which is
  # what the alias below points at and what makes rollback possible.
  publish = true

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      DATABASE_URL = data.aws_ssm_parameter.db_url.value
      ENVIRONMENT  = "staging"
      LOG_LEVEL    = "INFO"

      # The live parameter values, resolved at apply time and passed as one JSON
      # blob. The handler parses it and never makes a network call of its own.
      # See the data source above for why it is not read at runtime.
      #
      # Keys are the bare parameter names — "distance_bands_m", not the full
      # path — so the handler does not need to know the prefix.
      SEARCH_CONFIG = jsonencode(zipmap(
        [for n in data.aws_ssm_parameters_by_path.search.names : basename(n)],
        data.aws_ssm_parameters_by_path.search.values,
      ))
    }
  }

  tags = { Name = "${var.name_prefix}-api" }

  depends_on = [aws_cloudwatch_log_group.api]
}

# ----------------------------------------------------------------------- alias
# API Gateway integrates with THIS, never with the function directly. Pointing
# an integration at the function means it always runs $LATEST, and a rollback
# then has nothing to move.
resource "aws_lambda_alias" "live" {
  name             = "live"
  description      = "The version currently serving traffic. Moved by the deploy pipeline."
  function_name    = aws_lambda_function.api.function_name
  function_version = aws_lambda_function.api.version

  lifecycle {
    # The deploy pipeline moves this alias forward on every deploy. Without
    # this, the next `terraform apply` would drag it back to whatever version
    # Terraform last created — silently undoing a deployment.
    ignore_changes = [function_version]
  }
}

# ==============================================================================
# Fetch — the only Lambda in this project with internet access
# ==============================================================================
#
# NO vpc_config BLOCK. That absence is the design, not an omission.
#
# A Lambda with no VPC configuration runs on AWS-managed networking and can
# reach the internet. Attach it to our private subnet and it inherits a route
# table with no default route — it would hang trying to reach data.vic.gov.au,
# exactly as the API handler once hung trying to reach Parameter Store.
#
# The alternative is a NAT Gateway at roughly USD $40/month. Splitting ingestion
# into two functions costs nothing and buys the same thing. See ADR-002.
#
# The trade is real and worth naming: this function CANNOT reach RDS. It does
# not need to — it writes bytes to S3 and stops. Its sibling in load.tf does the
# database side from inside the VPC.
# ==============================================================================

data "archive_file" "fetch" {
  type = "zip"
  # data/ as the zip root, so the handler path is `ingestion.fetch.handler` and
  # the package layout in the repository is the package layout in the function.
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${var.name_prefix}-fetch.zip"

  # notebooks/ is exploratory work and is excluded from linting for the same
  # reason it is excluded here: it has no business in a deployment artefact.
  excludes = ["notebooks", "tests", ".venv", "__pycache__", "uv.lock", "pyproject.toml"]
}

resource "aws_cloudwatch_log_group" "fetch" {
  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems. This is a nine-week student project; 12
  #   months would outlive it while consuming the 5 GB CloudWatch free
  #   allowance.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month to
  #   encrypt logs about public open data that are already encrypted at rest
  #   with the CloudWatch service key.
  name              = "/aws/lambda/${var.name_prefix}-fetch"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.name_prefix}-fetch-logs" }
}

resource "aws_lambda_function" "fetch" {
  function_name = "${var.name_prefix}-fetch"
  description   = "Fetches one open-data source and lands it unmodified in the raw zone."

  role    = var.execution_role_arn
  handler = "ingestion.fetch.handler"
  runtime = var.runtime

  filename         = data.archive_file.fetch.output_path
  source_code_hash = data.archive_file.fetch.output_base64sha256

  # Small: this function reads a response into memory and writes it out. The
  # timeout is generous because government portals are slow, and it must exceed
  # the handler's own 20 s HTTP timeout so a slow publisher produces a readable
  # error rather than an opaque Lambda timeout.
  memory_size = var.fetch_memory_mb
  timeout     = var.fetch_timeout_seconds

  # checkov:skip=CKV_AWS_50:X-Ray tracing needs xray:PutTraceSegments on the
  #   execution role. That role is pre-built by the account holder and we can
  #   neither read nor change its policies, so enabling tracing would fail at
  #   runtime rather than at apply.
  # checkov:skip=CKV_AWS_116:This IS an asynchronous invocation, so unlike the
  #   API function a DLQ would genuinely catch something. Skipped anyway:
  #   EventBridge already retries three times over an hour, the fetch-failures
  #   alarm covers what survives that, and nothing is lost when a fetch fails —
  #   the file is still sitting on the publisher's server and re-invoking the
  #   function fetches it. A DLQ would need either an SQS queue nobody reads or
  #   sns:Publish on a role we cannot inspect.
  # checkov:skip=CKV_AWS_117:Deliberately NOT in the VPC — see the header. This
  # is the one function that requires internet egress.
  # checkov:skip=CKV_AWS_173:Environment variables here are a bucket name and a
  # map of public URLs. Encrypting them with a CMK would cost more than the data
  # is worth protecting.
  # checkov:skip=CKV_AWS_272:Code signing needs a signing profile and a CI
  # signing step. The deployment path is already OIDC-authenticated with no
  # long-lived credentials anywhere.
  # checkov:skip=CKV_AWS_115:Reserved concurrency cannot be set — this account's
  # total limit is 10 and the Free plan refuses to raise it. Documented in T2.

  environment {
    variables = {
      RAW_BUCKET = aws_s3_bucket.raw.id
      # Resolved by Terraform, same pattern as the API's SEARCH_CONFIG. A source
      # with an empty URL is carried through deliberately: the handler raises a
      # readable error naming the dataset, rather than silently doing nothing.
      SOURCES     = jsonencode({ for k, v in var.sources : k => v.url })
      ENVIRONMENT = var.environment
      LOG_LEVEL   = "INFO"
    }
  }

  tags       = { Name = "${var.name_prefix}-fetch" }
  depends_on = [aws_cloudwatch_log_group.fetch]
}

# ------------------------------------------------------------------------------
# Schedules — one rule per source
# ------------------------------------------------------------------------------
#
# One rule per source rather than one rule fanning out, because the cadences
# genuinely differ: three publishers are weekly and OSM is monthly. Encoding
# that in the schedule keeps it visible in the console, and means a single
# misbehaving source can be disabled without touching the others.
#
# THE TIMES ARE STAGGERED ON PURPOSE. This account's total Lambda concurrency is
# 10. Four simultaneous fetches of multi-megabyte files, plus whatever the API
# is doing, is a self-inflicted throttle. An hour apart costs nothing.
resource "aws_cloudwatch_event_rule" "fetch" {
  for_each = var.sources

  name        = "${var.name_prefix}-fetch-${each.key}"
  description = "Scheduled fetch for ${each.key}."

  schedule_expression = each.value.schedule_expression

  # A rule with no URL behind it is created but NOT armed. The shell is visible
  # in the console — so the Data team can see what is waiting for them — while
  # being unable to fire against a source nobody has configured.
  state = each.value.url == "" ? "DISABLED" : "ENABLED"

  tags = { Name = "${var.name_prefix}-fetch-${each.key}" }
}

resource "aws_cloudwatch_event_target" "fetch" {
  for_each = var.sources

  rule = aws_cloudwatch_event_rule.fetch[each.key].name
  arn  = aws_lambda_function.fetch.arn

  # The constant that tells one shared function which source it is fetching.
  # This is why four schedules need only one Lambda.
  input = jsonencode({ dataset = each.key })

  retry_policy {
    # A publisher that is down at 2am is often up at 3am. Retrying for an hour
    # turns a transient portal outage into a non-event rather than a missed
    # weekly refresh.
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }
}

# EventBridge cannot invoke a function unless the function's own resource policy
# permits it. Scoped to the specific rule ARN: without source_arn, ANY rule in
# this account could invoke it.
resource "aws_lambda_permission" "events" {
  for_each = var.sources

  statement_id  = "AllowFromEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fetch.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.fetch[each.key].arn
}

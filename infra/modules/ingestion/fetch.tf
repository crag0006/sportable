# ==============================================================================
# ingestion module — stage 1, fetch
# ==============================================================================
# Runs OUTSIDE the VPC. This is deliberate and it is the reason the module has
# no NAT gateway in it.
#
# The private subnets have no 0.0.0.0/0 route, by design — see the network
# module. A Lambda placed in them cannot reach data.vic.gov.au or the toilet map
# at all. Giving it one would mean a NAT gateway: about USD 45/month standing
# charge plus data, to serve four HTTPS GETs a week. Outside the VPC, the
# function reaches the publishers directly at no cost, and it needs nothing from
# inside the VPC — it writes to S3 and stops. The transform, which does need the
# database, is a separate function on the other side of an S3 event.
# ==============================================================================

data "archive_file" "fetch" {
  type        = "zip"
  source_dir  = var.fetch_source_dir
  output_path = "${path.module}/.build/fetch.zip"
}

resource "aws_lambda_function" "fetch" {
  # checkov:skip=CKV_AWS_272:Code signing requires an AWS Signer profile and a
  #   signing step in the pipeline. Disproportionate for a nine-week project.
  # checkov:skip=CKV_AWS_173:Environment variables are encrypted at rest with the
  #   AWS-managed Lambda key. A customer managed key adds ~USD $1/month and does
  #   not change who can read the configuration. No secret is stored here — the
  #   database URL is an SSM parameter NAME, resolved at runtime.
  # checkov:skip=CKV_AWS_115:Reserved concurrency cannot be set on this account.
  #   Its total Lambda concurrency limit is 10 and AWS rejects a reservation
  #   against a limit that low. See the api module for the same constraint.
  # checkov:skip=CKV_AWS_50:X-Ray tracing needs xray:PutTraceSegments on the
  #   execution role. That role is pre-built by the account holder and this
  #   account cannot create or amend IAM policies.
  # checkov:skip=CKV_AWS_116:A dead letter queue needs sqs:SendMessage on the
  #   execution role. The role is pre-built and this account cannot amend IAM
  #   policies, so a DLQ would be configured and then silently fail to deliver.
  #   Failures are caught by the Errors alarm in alarms.tf instead. Revisit if
  #   the role gains SQS permissions.
  # checkov:skip=CKV_AWS_117:Deliberately outside the VPC. The private subnets
  #   have no 0.0.0.0/0 route by design, so an in-VPC fetch cannot reach the
  #   publishers at all. Placing it inside would require a NAT gateway — ~USD
  #   45/month standing charge to serve four HTTPS GETs a week. It holds no
  #   credentials and touches nothing inside the VPC.

  function_name = "${var.name_prefix}-fetch"
  description   = "Stage 1: fetch registered sources into the raw zone."

  role          = var.execution_role_arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  # An immutable version per apply, matching the api module. A batch function
  # has no alias to move, but the version is what makes "put the old code back"
  # a one-call operation rather than a revert-and-redeploy.
  publish = true

  filename         = data.archive_file.fetch.output_path
  source_code_hash = data.archive_file.fetch.output_base64sha256

  timeout     = var.fetch_timeout_seconds
  memory_size = var.fetch_memory_mb

  environment {
    variables = {
      RAW_BUCKET = aws_s3_bucket.raw.id

      # handler.py defaults this to a path beside itself. Set explicitly because
      # the package layout is what makes it true, and a silent fallback here
      # would look like "no source cards found" at runtime.
      REGISTER_DIR = "/var/task/sources"

      SSE_ALGORITHM = "AES256"
      MAX_ATTEMPTS  = "3"
    }
  }

  # Not in a VPC. See the header.

  tags = merge(var.tags, { Name = "${var.name_prefix}-fetch" })

  depends_on = [aws_cloudwatch_log_group.fetch]
}

# Created explicitly rather than left to Lambda. An implicitly created log group
# has no retention set and bills for storage forever, and Terraform never learns
# it exists so it survives a destroy.
resource "aws_cloudwatch_log_group" "fetch" {
  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems, not a nine-week student staging environment.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month to
  #   encrypt logs already encrypted at rest with the CloudWatch service key.

  name              = "/aws/lambda/${var.name_prefix}-fetch"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Schedules
# ------------------------------------------------------------------------------
# EventBridge RULES, not EventBridge Scheduler. Scheduler invokes its target by
# assuming a role that must trust scheduler.amazonaws.com; this account cannot
# create roles, and the pipeline role trusts lambda.amazonaws.com only. A rule
# invokes through a resource-based policy on the function instead, which needs
# no role at all. Same cron, same constant payload, one less thing to request.

resource "aws_cloudwatch_event_rule" "fetch" {
  for_each = var.schedules

  name                = "${var.name_prefix}-fetch-${each.key}"
  description         = each.value.description
  schedule_expression = each.value.schedule_expression

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "fetch" {
  for_each = var.schedules

  rule      = aws_cloudwatch_event_rule.fetch[each.key].name
  target_id = "fetch"
  arn       = aws_lambda_function.fetch.arn

  # handler.py accepts {"source_ids": [...]}, attempts every id, and fails the
  # invocation at the end only if something actually failed. One rule can
  # therefore cover several sources without a DataVic outage also costing the
  # week's toilet map.
  input = jsonencode({
    source_ids = each.value.source_ids
  })

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }
}

resource "aws_lambda_permission" "fetch_from_events" {
  for_each = var.schedules

  statement_id  = "AllowExecutionFromEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fetch.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.fetch[each.key].arn
}

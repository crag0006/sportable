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
  function_name = "${var.name_prefix}-fetch"
  description   = "Stage 1: fetch registered sources into the raw zone."

  role    = var.execution_role_arn
  handler = "handler.handler"
  runtime = "python3.12"

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

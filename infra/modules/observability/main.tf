# ==============================================================================
# Observability — SNS topic and CloudWatch alarms
# ==============================================================================
#
# THE TEST THIS MODULE HAS TO PASS
#   T5's definition of done is one sentence: "you break something on purpose and
#   an email arrives." Not "a dashboard exists." A dashboard is something you
#   have to remember to look at, and nobody looks at one during an assessment
#   week. An alarm comes to you.
#
# WHAT IS DELIBERATELY NOT HERE
#   No dashboard, no X-Ray, no custom metrics, no anomaly detection. Six alarms
#   on metrics AWS already publishes for free. Every one of them answers a
#   question someone would actually ask at 2am, and none of them fires on a
#   healthy system — an alarm that cries wolf is worse than no alarm, because
#   the team learns to delete the email unread.
#
# LOG RETENTION IS NOT HERE EITHER
#   It belongs with the thing that produces the logs, so each module sets its
#   own: modules/api and modules/database both create their log group with
#   retention_in_days BEFORE the resource that writes to it. That ordering
#   matters — let Lambda create the group implicitly and it defaults to "never
#   expire", which quietly consumes the 5 GB free tier and then bills forever.
# ==============================================================================

# ------------------------------------------------------------------------------
# Where alarms go
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name         = "${var.name_prefix}-alerts"
  display_name = "SportAble staging alerts"

  # checkov:skip=CKV_AWS_26:Encryption at rest needs a customer-managed KMS key
  # (~USD $1/month). This topic carries alarm names and metric values — no
  # personal data and no credentials — on a student staging environment with a
  # near-zero budget. Revisit for production.

  tags = { Name = "${var.name_prefix}-alerts" }
}

# Email, not SMS or a chat webhook. SMS costs money and needs a spending limit
# raised on this account; a webhook needs a secret in Terraform state. Email is
# free, and everyone already has it on their phone.
#
# EACH SUBSCRIBER MUST CLICK A CONFIRMATION LINK. Terraform creates the
# subscription in `pending confirmation` and AWS sends the email. Until someone
# clicks, that address receives nothing — and Terraform will happily report
# success, because the subscription resource genuinely was created.
#
# This is the single most common way a team discovers, during an incident, that
# their alerting never worked. Verify with the command in the runbook.
resource "aws_sns_topic_subscription" "email" {
  for_each = toset(var.alert_emails)

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = each.value

  # The confirmation state lives with the subscriber, not in our configuration.
  # Without this, a plan taken before someone confirms proposes replacing the
  # subscription and resetting them to unconfirmed.
  lifecycle {
    ignore_changes = [confirmation_timeout_in_minutes]
  }
}

# ------------------------------------------------------------------------------
# Lambda
# ------------------------------------------------------------------------------

# Any unhandled exception. Threshold 1, not 5 — on a system serving a handful of
# demo requests, one error is a real proportion of traffic, and waiting for five
# means waiting for a pattern that may never form before the demo.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name        = "${var.name_prefix}-lambda-errors"
  alarm_description = "The API function raised an unhandled exception. Check /aws/lambda/${var.function_name}."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = var.function_name }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  # No invocations publishes no datapoints. Without this the alarm sits in
  # INSUFFICIENT_DATA all night and you cannot tell "quiet" from "broken".
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${var.name_prefix}-lambda-errors" }
}

# This account's TOTAL concurrent execution limit is 10 — the AWS Free plan
# refuses to raise it, which is also why reserved concurrency could not be set
# on the function. Ten concurrent requests is plausible during a live demo with
# six people clicking, so a throttle here is a realistic failure, not a
# theoretical one.
resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  alarm_name        = "${var.name_prefix}-lambda-throttles"
  alarm_description = "Requests were rejected before running. Account concurrency limit is 10 and cannot be raised on the Free plan."

  namespace   = "AWS/Lambda"
  metric_name = "Throttles"
  dimensions  = { FunctionName = var.function_name }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${var.name_prefix}-lambda-throttles" }
}

# Warns BEFORE the timeout starts cutting requests off. The function's timeout is
# 10 s; this fires at 8 s average, which on a p50-ish statistic means something
# is badly wrong — almost certainly a database connection that is hanging rather
# than failing fast.
resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  alarm_name        = "${var.name_prefix}-lambda-duration"
  alarm_description = "Average duration is approaching the ${var.function_timeout_seconds}s timeout. Usually a database connection hanging rather than failing."

  namespace   = "AWS/Lambda"
  metric_name = "Duration"
  dimensions  = { FunctionName = var.function_name }

  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.function_timeout_seconds * 1000 * 0.8
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${var.name_prefix}-lambda-duration" }
}

# ------------------------------------------------------------------------------
# API Gateway
# ------------------------------------------------------------------------------

# 5xx only. A 4xx is the client asking for something that is not there — our
# own smoke test deliberately requests a nonexistent venue on every deploy, and
# alarming on that would page us for a passing test.
#
# HTTP APIs publish "5xx", not "5XXError" — that is the REST API metric name and
# using it here produces an alarm that silently never fires.
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name        = "${var.name_prefix}-api-5xx"
  alarm_description = "API Gateway returned server errors. Check the access log group for integrationErrorMessage."

  namespace   = "AWS/ApiGateway"
  metric_name = "5xx"
  dimensions  = { ApiId = var.api_id }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${var.name_prefix}-api-5xx" }
}

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

# db.t4g.micro allows roughly 112 connections. Lambda opens one per execution
# environment and keeps it, so connections track concurrency, not requests — and
# a handler that forgets to close them climbs steadily until the database
# refuses everything at once.
#
# 40 gives a wide margin and still fires long before anything breaks. This is the
# alarm most likely to matter once real handlers land: connection pooling is on
# Backend's list and is easy to defer.
resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name        = "${var.name_prefix}-rds-connections"
  alarm_description = "Connection count climbing on db.t4g.micro (~112 max). Suspect a handler not releasing connections."

  namespace   = "AWS/RDS"
  metric_name = "DatabaseConnections"
  dimensions  = { DBInstanceIdentifier = var.db_instance_identifier }

  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.db_connection_threshold
  comparison_operator = "GreaterThanThreshold"

  # A STOPPED instance publishes nothing. Staging is stopped most evenings to
  # save money, and "missing" must not read as "breaching" or the team gets an
  # email every night for doing the right thing.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${var.name_prefix}-rds-connections" }
}

# 20 GB allocated with autoscaling off — deliberately, so a runaway ingestion job
# cannot quietly grow the bill. That choice makes running out of space a real
# possibility, so it needs an alarm. Bytes, not gigabytes: CloudWatch publishes
# FreeStorageSpace in bytes and the unit is an easy, silent mistake.
resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name        = "${var.name_prefix}-rds-free-storage"
  alarm_description = "Less than ${var.db_free_storage_threshold_gb} GB free. Storage autoscaling is off by design, so this will not fix itself."

  namespace   = "AWS/RDS"
  metric_name = "FreeStorageSpace"
  dimensions  = { DBInstanceIdentifier = var.db_instance_identifier }

  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.db_free_storage_threshold_gb * 1024 * 1024 * 1024
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = { Name = "${var.name_prefix}-rds-free-storage" }
}

# ==============================================================================
# ingestion module — alarms
# ==============================================================================
# Three Errors alarms, one per function, and nothing else by default. CloudWatch
# allows ten alarms on the Free Tier and this stack already uses six; three more
# reaches nine. The duration and hash-pin alarms are real but optional and sit
# behind enable_extended_alarms because turning them on costs the allowance.
#
# The pipeline runs weekly and unattended. Nobody watches it. An alarm that
# fires on a real problem is the only difference between "the data is three
# weeks stale" being noticed and being discovered by a marker.
#
# handler.py emits one structured JSON line per notable event with an `event`
# field. The metric filters below key off that field, which turns a hash pin
# mismatch from a line someone has to happen to read into a graphable metric.
# ==============================================================================

locals {
  alarm_actions = var.alarm_topic_arn == "" ? [] : [var.alarm_topic_arn]

  functions = {
    fetch  = aws_lambda_function.fetch.function_name
    load   = aws_lambda_function.load.function_name
    derive = aws_lambda_function.derive.function_name
  }
}

# Any invocation error. handler.py raises at the end of a run if any source
# failed, so this covers a publisher outage, a licence gate failure and a
# withdrawn resource alike.
resource "aws_cloudwatch_metric_alarm" "errors" {
  for_each = local.functions

  alarm_name        = "${each.value}-errors"
  alarm_description = "One or more invocations of ${each.value} failed."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  statistic   = "Sum"

  dimensions = {
    FunctionName = each.value
  }

  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  # A weekly function emits no datapoints for six days. Treating missing data as
  # breaching would alarm continuously; as notBreaching, correctly, it says
  # nothing until an invocation actually fails.
  treat_missing_data = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = var.tags
}

# A run that finishes just inside the timeout today fails outright next month
# when a publisher is slower. Alarming at 80% gives a month's warning.
resource "aws_cloudwatch_metric_alarm" "duration" {
  for_each = var.enable_extended_alarms ? local.functions : {}

  alarm_name        = "${each.value}-duration-near-timeout"
  alarm_description = "${each.value} is running close to its configured timeout."

  namespace   = "AWS/Lambda"
  metric_name = "Duration"
  statistic   = "Maximum"

  dimensions = {
    FunctionName = each.value
  }

  period              = 300
  evaluation_periods  = 1
  threshold           = var.fetch_timeout_seconds * 1000 * 0.8
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Metric filters on the structured log
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "hash_pin_mismatch" {
  name           = "${var.name_prefix}-hash-pin-mismatch"
  log_group_name = aws_cloudwatch_log_group.fetch.name

  pattern = "{ $.event = \"HASH_PIN_MISMATCH\" }"

  metric_transformation {
    name      = "HashPinMismatch"
    namespace = "SportAble/Ingestion"
    value     = "1"
    unit      = "Count"
  }
}

# A pinned hash that stops matching means the publisher changed a file we had
# asserted was fixed. It is not an error — the fetch succeeds — but it
# invalidates the reproducibility claim in the DMP until someone looks.
resource "aws_cloudwatch_metric_alarm" "hash_pin_mismatch" {
  count = var.enable_extended_alarms ? 1 : 0

  alarm_name        = "${var.name_prefix}-hash-pin-mismatch"
  alarm_description = "A source's payload no longer matches its pinned SHA-256."

  namespace   = "SportAble/Ingestion"
  metric_name = aws_cloudwatch_log_metric_filter.hash_pin_mismatch.metric_transformation[0].name
  statistic   = "Sum"

  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions

  tags = var.tags
}

resource "aws_cloudwatch_log_metric_filter" "fetch_failed" {
  name           = "${var.name_prefix}-fetch-failed"
  log_group_name = aws_cloudwatch_log_group.fetch.name

  pattern = "{ $.event = \"FETCH_FAILED\" }"

  metric_transformation {
    name      = "FetchFailed"
    namespace = "SportAble/Ingestion"
    value     = "1"
    unit      = "Count"
  }
}

# ==============================================================================
# Ingestion alarms
# ==============================================================================
#
# The plan's wording is "alarm after three failures". That is deliberate and
# differs from the API alarms in T5, which fire on ONE error.
#
# The reason is what a failure means in each case. One API error is a user
# seeing a broken page right now. One fetch failure is a government portal
# having a bad morning — and EventBridge already retries three times over an
# hour. Alarming on the first attempt would page us for something the retry
# policy is about to fix by itself.
#
# Three failures inside a day means the retries did not help, which is a real
# problem: the weekly refresh will be missed.
# ==============================================================================

resource "aws_cloudwatch_metric_alarm" "fetch_failures" {
  alarm_name        = "${var.name_prefix}-fetch-failures"
  alarm_description = "Three or more fetch failures in a day. EventBridge retries three times over an hour, so this means the retries did not help."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = aws_lambda_function.fetch.function_name }

  statistic = "Sum"
  # A day, not five minutes. These functions run weekly; a five-minute window
  # would almost always be empty and the alarm would say nothing.
  period              = 86400
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"

  # Silence is the normal state for a weekly job. Without this the alarm sits in
  # INSUFFICIENT_DATA for six days out of seven.
  treat_missing_data = "notBreaching"

  alarm_actions = [var.alerts_topic_arn]
  ok_actions    = [var.alerts_topic_arn]

  tags = { Name = "${var.name_prefix}-fetch-failures" }
}

# The load function is triggered by an object landing, so ANY error means a file
# arrived and was not processed. Threshold 1, unlike fetch: there is no retry
# policy behind this one, and a silently unprocessed file is how the database
# stays empty while every dashboard looks fine.
resource "aws_cloudwatch_metric_alarm" "load_failures" {
  alarm_name        = "${var.name_prefix}-load-failures"
  alarm_description = "A raw object landed and was not processed. Check /aws/lambda/${var.name_prefix}-load."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = aws_lambda_function.load.function_name }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [var.alerts_topic_arn]
  ok_actions    = [var.alerts_topic_arn]

  tags = { Name = "${var.name_prefix}-load-failures" }
}

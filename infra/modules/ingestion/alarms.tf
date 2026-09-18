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

# ==============================================================================
# DS-09 (AAA Play) — the one source that is somebody else's running website
# ==============================================================================
# WHY THIS SOURCE GETS ALARMS OF ITS OWN
#   Eight of the nine sources are file downloads from government portals. They
#   have a licence, a publication schedule, a stated last-updated date and, for
#   most of them, a SHA-256 pinned in the source card. When one of those breaks
#   it breaks loudly: a 404, a licence gate, a hash that stops matching.
#
#   DS-09 is a live WordPress REST API on Reclink's own marketing site, behind
#   Wordfence, unversioned, with no agreement with this project. It can change
#   shape on a plugin update and tell nobody. The card already records one such
#   surprise — the dated `event` post type is not registered for REST and
#   answers 404 — and eighteen requests per pull is eighteen chances to be rate
#   limited, redirected or served HTML where JSON was expected.
#
# WHY STALENESS IS THE FAILURE THAT MATTERS HERE, NOT ABSENCE
#   Every other source describes a thing that stays put. A toilet block that
#   was accessible last week is accessible this week, so week-old DS-02 data is
#   merely old. DS-09 describes PROGRAMMES — a weekday, a time, a venue, a
#   registration link — and a programme that ended is not old data, it is wrong
#   data. A user with limited mobility who arranges transport, a support worker
#   and a carer to attend a session that stopped running in March has been
#   actively harmed by our page. An empty events list would have been kinder.
#
#   That is the whole reason these two alarms are on by default rather than
#   behind enable_extended_alarms. They take this module from three always-on
#   alarms to five and the stack from nine to eleven, one past the CloudWatch
#   Free Tier allowance of ten, at USD $0.10 per alarm per month. Twenty cents
#   a month is the correct price for not sending someone across Melbourne to a
#   locked door.
#
# WHAT IS DELIBERATELY NOT COVERED, AND WHY
#   The alarm this section would most like to have is the literal one: "no
#   successful DS-09 load in the last 14 days", 14 being the staleness
#   threshold this environment publishes at
#   /sportable/<env>/data/staleness_days/aaaplay. CloudWatch cannot express it.
#   An alarm's total evaluation range is capped at one day — PutMetricAlarm
#   requires EvaluationPeriods multiplied by Period to be 86,400 seconds or
#   less — so the longest window a metric alarm can look back over is 24 hours,
#   and 24 hours of silence from a WEEKLY pipeline is the normal case six days
#   out of seven. Setting treat_missing_data to breaching to force it would
#   page on Monday, Tuesday, Wednesday, Thursday, Friday and Saturday, and an
#   alarm that cries wolf six days a week is worse than no alarm: it trains the
#   one person watching to ignore it.
#
#   Doing it properly means a small scheduled function that publishes "hours
#   since the last successful DS-09 load" as a gauge, which an alarm can then
#   read inside a one-day window. That needs a new execution role, and this
#   account's principals hold PowerUserAccess, which excludes IAM entirely —
#   the same constraint recorded at the top of variables.tf and the reason this
#   module takes every role as an ARN. It is a real gap, recorded rather than
#   papered over.
#
#   Two consequences are therefore carried elsewhere, not here:
#     * The 14-day threshold is enforced in the PRODUCT layer. The API reads it
#       from Parameter Store and every fact carries possibly_out_of_date, so a
#       stale programme is labelled on screen even when no alarm fired. See
#       backend/app/domain/provenance.py and modules/app_config.
#     * The DS-09 EventBridge rule being DISABLED — by hand, as the T4 runbook
#       shows rules being disabled — produces permanent silent staleness that
#       nothing below detects, for the same one-day-window reason. It is a
#       checklist item in the runbook, not an alarm.
# ------------------------------------------------------------------------------

# The fetch never reached usable JSON: a timeout, a 403 from Wordfence, a
# redirect to an HTML error page, a page past the end of the collection.
# handler.py logs FETCH_FAILED with the source id before it re-raises.
resource "aws_cloudwatch_log_metric_filter" "ds09_fetch_failed" {
  name           = "${var.name_prefix}-ds09-fetch-failed"
  log_group_name = aws_cloudwatch_log_group.fetch.name

  # Both conditions matter. The generic FetchFailed filter above counts every
  # source together, which cannot answer "is the events page about to go
  # stale?" — DS-09 is the only source whose failure has that consequence.
  pattern = "{ $.event = \"FETCH_FAILED\" && $.source_id = \"DS-09\" }"

  metric_transformation {
    name      = "Ds09FetchFailed"
    namespace = "SportAble/Ingestion"
    value     = "1"
    unit      = "Count"
  }
}

# This OVERLAPS the fetch Errors alarm on purpose. Errors says "a fetch run
# failed" and stops there; on a Sunday when four rules ran, finding out which
# source it was means opening the log. This one names DS-09 in the alarm, which
# is the difference between acting on it before the next Sunday and reading
# about it afterwards. DS-09 has a rule to itself precisely so that this
# distinction stays clean — see the schedules map in variables.tf.
resource "aws_cloudwatch_metric_alarm" "ds09_fetch_failed" {
  alarm_name        = "${var.name_prefix}-ds09-fetch-failed"
  alarm_description = "The weekly AAA Play (DS-09) pull failed. The events page will not refresh this week."

  namespace   = "SportAble/Ingestion"
  metric_name = aws_cloudwatch_log_metric_filter.ds09_fetch_failed.metric_transformation[0].name
  statistic   = "Sum"

  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  # Same reasoning as the Errors alarm: a weekly pipeline emits nothing for six
  # days, so missing data is the normal state and must not breach.
  treat_missing_data = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = var.tags
}

# The fetch succeeded and the load did not. This is the freshness alarm the
# pipeline CAN see: 15.4 MB of fresh AAA Play JSON is sitting in the raw zone,
# the transaction rolled back, and the database still holds last week's
# programmes with nothing to say they were not replaced. It is the most likely
# shape of a third-party schema change — the transformer meets a field that is
# suddenly null, or a taxonomy term id that no longer resolves — and it is
# exactly the case where the page keeps serving confident, wrong dates.
#
# loaders/handler.py logs LOAD_ABORTED with the source id and re-raises, so the
# load function's Errors alarm fires too. As above, that one cannot name the
# source and this one can.
resource "aws_cloudwatch_log_metric_filter" "ds09_load_aborted" {
  name           = "${var.name_prefix}-ds09-load-aborted"
  log_group_name = aws_cloudwatch_log_group.load.name

  pattern = "{ $.event = \"LOAD_ABORTED\" && $.source_id = \"DS-09\" }"

  metric_transformation {
    name      = "Ds09LoadAborted"
    namespace = "SportAble/Ingestion"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "ds09_load_aborted" {
  alarm_name        = "${var.name_prefix}-ds09-data-stale"
  alarm_description = "A fresh AAA Play (DS-09) payload landed and did not load. Displayed programmes are now older than the raw zone — treat as stale, not merely absent."

  namespace   = "SportAble/Ingestion"
  metric_name = aws_cloudwatch_log_metric_filter.ds09_load_aborted.metric_transformation[0].name
  statistic   = "Sum"

  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = var.tags
}

# No alarm on this one, deliberately. It is the positive signal — the datapoint
# that says a DS-09 load closed successfully — and its VALUE is never
# interesting; only the timestamp of the most recent one is, which is the
# 14-day question CloudWatch alarms cannot ask. It exists so that question can
# be answered in one graph, or in one get-metric-statistics call from the
# runbook, instead of by paging through a log group.
resource "aws_cloudwatch_log_metric_filter" "ds09_load_succeeded" {
  name           = "${var.name_prefix}-ds09-load-succeeded"
  log_group_name = aws_cloudwatch_log_group.load.name

  pattern = "{ $.event = \"LOAD_RUN_CLOSED\" && $.source_id = \"DS-09\" }"

  metric_transformation {
    name      = "Ds09LoadSucceeded"
    namespace = "SportAble/Ingestion"
    value     = "1"
    unit      = "Count"
  }
}

# ------------------------------------------------------------------------------
# Rejection rate — the abort, and the approach to it
# ------------------------------------------------------------------------------
# Two alarms for one condition, because they answer different questions.
#
# The ABORT alarm fires when a load crossed its threshold and stopped. Thresholds
# are 15% by default and 30% for DS-01, and those numbers are not arbitrary: the
# DS-01 source card documents that 14 of its 52 in-area venues (26.92%) publish
# no coordinates, so a 15% bar would stop a load that is behaving exactly as the
# card says it should. The thresholds live in loader.py next to that reasoning.
#
# The APPROACH alarm fires below the threshold. Without it the only signal is a
# load that already failed, which means a publisher drifting toward the cliff is
# invisible until it goes over. loader.py emits the rate on every completed load
# so this can watch the trend.
#
# The ds09-load-aborted filter above is deliberately NOT replaced by these: it is
# scoped to DS-09 and carries a different meaning (fresh payload landed, nothing
# loaded, so what is served is STALE rather than merely unchanged). These two are
# register-wide and mean "the transform and the publisher disagree".
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "load_aborted_any" {
  name           = "${var.name_prefix}-load-aborted-any"
  log_group_name = aws_cloudwatch_log_group.load.name

  pattern = "{ $.event = \"LOAD_ABORTED\" }"

  metric_transformation {
    name      = "LoadAborted"
    namespace = "SportAble/Ingestion"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "load_aborted_any" {
  alarm_name        = "${var.name_prefix}-load-aborted"
  alarm_description = "A load exceeded its rejection threshold and stopped. Rejected rows are in the quarantine bucket, NOT the quarantine table — the abort rolls the transaction back. Diagnose before rerunning; do not raise the threshold to make it pass."

  namespace   = "SportAble/Ingestion"
  metric_name = aws_cloudwatch_log_metric_filter.load_aborted_any.metric_transformation[0].name
  statistic   = "Sum"

  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = var.tags
}

# The rate itself, published by loader.py on every load that completes. Unlike
# the filters above this extracts a VALUE rather than counting occurrences, so
# the alarm can watch the trend rather than a single event.
resource "aws_cloudwatch_log_metric_filter" "quarantine_rate" {
  name           = "${var.name_prefix}-ds09-quarantine-rate"
  log_group_name = aws_cloudwatch_log_group.load.name

  # LOAD_RUN_CLOSED, not an event invented for this alarm: handler.py already
  # logs the rate on every load that commits. Reusing it means the metric cannot
  # drift from what the loader actually reports.
  pattern = "{ $.event = \"LOAD_RUN_CLOSED\" && $.source_id = \"DS-09\" && $.quarantine_rate_pct = * }"

  metric_transformation {
    name      = "Ds09QuarantineRatePct"
    namespace = "SportAble/Ingestion"
    value     = "$.quarantine_rate_pct"
    unit      = "Percent"
  }
}

resource "aws_cloudwatch_metric_alarm" "quarantine_rate_approaching" {
  alarm_name        = "${var.name_prefix}-ds09-quarantine-rate-approaching"
  alarm_description = "A DS-09 load committed but rejected more rows than usual. Below the 15% abort threshold so nothing failed — this is AAA Play or the transform drifting, seen before it stops a load."

  namespace   = "SportAble/Ingestion"
  metric_name = aws_cloudwatch_log_metric_filter.quarantine_rate.metric_transformation[0].name
  statistic   = "Maximum"

  # SCOPED TO DS-09 ON PURPOSE, and a register-wide version would be wrong.
  # DS-01 quarantines a documented 26.92% of its in-area rows because that share
  # publishes no coordinates, so any threshold useful as an early warning for
  # DS-09 would fire on every DS-01 load forever. An alarm that is always red is
  # an alarm nobody reads.
  #
  # Scoping it is also honest about what is automated: after the Iteration 2
  # scope decision, DS-09 is the ONLY source on a schedule. The rest are loaded
  # once by hand through load_run.py, which does not write to this log group at
  # all. A second automated source needs its own baseline and its own filter,
  # taken from a real run the way DS-01's 30% was.
  #
  # Ten per cent sits under the 15% abort with room to act. Maximum over a day
  # rather than per load, because DS-09 runs weekly and one spike is the signal.
  period              = 86400
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
  ok_actions    = local.alarm_actions

  tags = var.tags
}

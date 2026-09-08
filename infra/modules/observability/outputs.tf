output "topic_arn" {
  description = "Alerts topic. T4's ingestion alarms should publish here too."
  value       = aws_sns_topic.alerts.arn
}

output "alarm_names" {
  description = "Every alarm this module manages."
  value = [
    aws_cloudwatch_metric_alarm.lambda_errors.alarm_name,
    aws_cloudwatch_metric_alarm.lambda_throttles.alarm_name,
    aws_cloudwatch_metric_alarm.lambda_duration.alarm_name,
    aws_cloudwatch_metric_alarm.api_5xx.alarm_name,
    aws_cloudwatch_metric_alarm.rds_connections.alarm_name,
    aws_cloudwatch_metric_alarm.rds_storage.alarm_name,
  ]
}

output "subscription_check_command" {
  description = "Run this after applying. Any PendingConfirmation means that address is deaf."
  value       = "aws sns list-subscriptions-by-topic --topic-arn ${aws_sns_topic.alerts.arn} --query 'Subscriptions[].[Endpoint,SubscriptionArn]' --output table"
}

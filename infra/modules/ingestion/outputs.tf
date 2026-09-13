# ==============================================================================
# ingestion module — outputs
# ==============================================================================
# The bucket names are here because an operator needs them for `aws s3 ls` when
# a load has gone wrong. The function names are here so the observability module
# can be extended to cover the pipeline without reaching into this module.
# ==============================================================================

output "raw_bucket" {
  description = "Raw zone bucket name. The immutable, dated archive."
  value       = aws_s3_bucket.raw.id
}

output "raw_bucket_arn" {
  value = aws_s3_bucket.raw.arn
}

output "quarantine_bucket" {
  description = "Quarantine bucket name. Rows that failed validation, with reasons."
  value       = aws_s3_bucket.quarantine.id
}

output "fetch_function_name" {
  description = "For `aws lambda invoke` when running a source by hand."
  value       = aws_lambda_function.fetch.function_name
}

output "load_function_name" {
  value = aws_lambda_function.load.function_name
}

output "derive_function_name" {
  value = aws_lambda_function.derive.function_name
}

output "schedule_rule_names" {
  description = "EventBridge rule names, for disabling a schedule during an incident."
  value       = [for rule in aws_cloudwatch_event_rule.fetch : rule.name]
}

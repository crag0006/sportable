output "raw_bucket" {
  description = "Drop a file here and the load function processes it — the manual fallback path."
  value       = aws_s3_bucket.raw.id
}

output "quarantine_bucket" {
  value = aws_s3_bucket.quarantine.id
}

output "fetch_function_name" {
  value = aws_lambda_function.fetch.function_name
}

output "load_function_name" {
  value = aws_lambda_function.load.function_name
}

output "schedules" {
  description = "Each rule and whether it is armed. A source with no URL is created DISABLED."
  value = {
    for k, r in aws_cloudwatch_event_rule.fetch : k => {
      schedule = r.schedule_expression
      state    = r.state
    }
  }
}

output "smoke_test_command" {
  description = <<-EOT
    Proves the whole path without depending on a publisher: fetch reaches the
    internet, writes to S3, the notification fires, and the load function reads
    it back from inside the VPC through the gateway endpoint.
  EOT
  value = join(" ", [
    "aws lambda invoke --function-name ${aws_lambda_function.fetch.function_name}",
    "--payload '{\"dataset\":\"vic_sport_rec\",\"url\":\"https://checkip.amazonaws.com/\"}'",
    "--cli-binary-format raw-in-base64-out /dev/stdout",
  ])
}

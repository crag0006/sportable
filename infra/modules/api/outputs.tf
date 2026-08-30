output "function_name" {
  value = aws_lambda_function.api.function_name
}

output "function_arn" {
  value = aws_lambda_function.api.arn
}

output "function_version" {
  description = <<-EOT
    The immutable version number `terraform apply` just published, e.g. "7".

    The deploy pipeline needs this. `publish = true` mints a new version
    whenever the zip's hash changes, but the `live` alias deliberately does NOT
    follow it — see the lifecycle block in main.tf. Moving the alias is the
    pipeline's job, so that database migrations can run in the gap between
    "new code exists" and "new code serves traffic".

    Reading the number from a Terraform output is deterministic. The
    alternative — asking Lambda for its highest-numbered version — is a guess
    that goes wrong the moment two deploys overlap.
  EOT
  value       = aws_lambda_function.api.version
}

output "alias_arn" {
  description = "What API Gateway integrates with. Never the function ARN."
  value       = aws_lambda_alias.live.arn
}

output "alias_name" {
  value = aws_lambda_alias.live.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.api.name
}

output "invoke_test_command" {
  description = "Prove the function works before API Gateway is involved."
  value       = "aws lambda invoke --function-name ${aws_lambda_alias.live.arn} --payload '{}' --cli-binary-format raw-in-base64-out /dev/stdout"
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = <<-EOT
    Direct API Gateway URL. Useful for debugging, but NOT the address the
    application uses — traffic reaches the API through CloudFront so that the
    SPA and the API share one origin and CORS never applies.
  EOT
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_domain" {
  description = <<-EOT
    Hostname only, for use as a CloudFront origin.

    invoke_url is "https://<id>.execute-api.<region>.amazonaws.com/" — note the
    TRAILING SLASH. A CloudFront origin domain_name must be a bare hostname, so
    both the scheme and that slash have to come off.
  EOT
  value       = trimsuffix(replace(aws_apigatewayv2_stage.default.invoke_url, "https://", ""), "/")
}

output "access_log_group" {
  value = aws_cloudwatch_log_group.gateway.name
}

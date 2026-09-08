output "parameter_names" {
  description = "Every parameter this module manages. Useful for a smoke test."
  value = concat(
    [
      aws_ssm_parameter.distance_bands.name,
      aws_ssm_parameter.default_band.name,
      aws_ssm_parameter.max_results.name,
    ],
    [for p in aws_ssm_parameter.staleness : p.name],
  )
}

output "read_policy_arn_hint" {
  description = <<-EOT
    The IAM permission the Lambda execution role needs to read this tree.
    We cannot attach it — that role is managed by the account holder — so this
    output exists to be pasted into the request.
  EOT
  value       = "ssm:GetParametersByPath on arn:aws:ssm:*:*:parameter${var.ssm_prefix}/*"
}

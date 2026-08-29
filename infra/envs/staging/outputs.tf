output "vpc_id" {
  value = module.network.vpc_id
}

output "private_subnet_ids" {
  value = module.network.private_subnet_ids
}

output "public_subnet_id" {
  value = module.network.public_subnet_id
}

output "security_group_ids" {
  value = {
    bastion = module.network.bastion_security_group_id
    lambda  = module.network.lambda_security_group_id
    rds     = module.network.rds_security_group_id
  }
}

output "private_route_table_id" {
  description = "Check this has no 0.0.0.0/0 route after every apply."
  value       = module.network.private_route_table_id
}

# Database — connection details only. The password and connection string are in
# SSM and deliberately never surfaced here: Terraform outputs are printed to the
# console and to CI logs.
output "db_endpoint" {
  description = "host:port for the SSH tunnel."
  value       = module.database.endpoint
}

output "db_instance_identifier" {
  description = "For stopping the instance when you finish for the day."
  value       = module.database.instance_identifier
}

output "db_ssm_url_parameter" {
  description = "Read with: aws ssm get-parameter --name <this> --with-decryption"
  value       = module.database.ssm_url_parameter
}

# Bastion — the tunnel is how anyone reaches the database.
output "bastion_instance_id" {
  description = "Stop this when you finish for the day."
  value       = module.bastion.instance_id
}

output "bastion_public_ip" {
  description = "Changes on every stop/start. Re-read it after starting."
  value       = module.bastion.public_ip
}

output "db_tunnel_command" {
  description = <<-EOT
    Open the tunnel, then localhost:5433 is the staging database.

    Stop the local Docker container first, or port 5433 is already taken.
  EOT
  value = format(
    "ssh -i ~/.ssh/sportable -L 5433:%s:%d ec2-user@%s",
    module.database.address,
    module.database.port,
    module.bastion.public_ip,
  )
}

# The demo URL. This is what the Definition of Done means by "demonstrated from
# that URL rather than from a laptop".
output "site_url" {
  description = "Public HTTPS address of the application."
  value       = module.static_site.site_url
}

output "site_bucket" {
  description = "Deploy target: aws s3 sync frontend/dist s3://<this>/"
  value       = module.static_site.bucket_name
}

output "cloudfront_distribution_id" {
  description = "For cache invalidation after each deploy."
  value       = module.static_site.distribution_id
}

output "api_function_name" {
  value = module.api.function_name
}

output "api_alias_arn" {
  description = "API Gateway integrates with this, not the function itself."
  value       = module.api.alias_arn
}

output "api_invoke_test_command" {
  description = "Run this to prove the Lambda works before API Gateway exists."
  value       = module.api.invoke_test_command
}

output "api_endpoint" {
  description = "Direct API Gateway URL — for debugging. The app uses the CloudFront path."
  value       = module.api.api_endpoint
}

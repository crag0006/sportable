# NOTE what is absent: the password, and the connection string. Both live in SSM
# and must never become Terraform outputs — outputs are printed to the console
# and to CI logs.

output "endpoint" {
  description = "host:port, for the SSH tunnel."
  value       = aws_db_instance.this.endpoint
}

output "address" {
  description = "Hostname only. Use this as the tunnel's remote host."
  value       = aws_db_instance.this.address
}

output "port" {
  value = aws_db_instance.this.port
}

output "database_name" {
  value = aws_db_instance.this.db_name
}

output "instance_identifier" {
  description = "For `aws rds stop-db-instance --db-instance-identifier ...`."
  value       = aws_db_instance.this.identifier
}

output "ssm_url_parameter" {
  description = "SSM path holding the connection string. Pass to Alembic as SSM_DB_URL_PARAM."
  value       = aws_ssm_parameter.db_url.name
}

output "ssm_password_parameter" {
  value = aws_ssm_parameter.db_password.name
}

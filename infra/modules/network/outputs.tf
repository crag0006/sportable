# ==============================================================================
# network module — outputs
# ==============================================================================
# These are the module's public interface. The database, api and ingestion
# modules consume them; nothing else about this module's internals is visible.
# ==============================================================================

output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "public_subnet_id" {
  description = "Public subnet, for the bastion."
  value       = aws_subnet.public.id
}

output "private_subnet_ids" {
  description = <<-EOT
    Both private subnets, ordered to match `azs`. Pass the whole list to the RDS
    subnet group — it needs two AZs — and the first element to Lambda.
  EOT
  value       = [for az in var.azs : aws_subnet.private[az].id]
}

output "bastion_security_group_id" {
  description = "Attach to the bastion instance."
  value       = aws_security_group.bastion.id
}

output "lambda_security_group_id" {
  description = "Attach to every in-VPC Lambda function."
  value       = aws_security_group.lambda.id
}

output "rds_security_group_id" {
  description = "Attach to the RDS instance."
  value       = aws_security_group.rds.id
}

output "private_route_table_id" {
  description = "Private route table. Assert in tests that it has no 0.0.0.0/0 route."
  value       = aws_route_table.private.id
}

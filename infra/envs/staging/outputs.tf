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

variable "name_prefix" {
  description = "Prefix for resource names, e.g. \"sportable-staging\"."
  type        = string
}

variable "subnet_ids" {
  description = <<-EOT
    Both private subnet ids, from the network module.

    RDS requires a DB subnet group spanning at least two Availability Zones even
    for a single-AZ instance, so it can fail over if it ever has to. This is why
    the network module builds a second private subnet that holds nothing.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "RDS subnet groups require at least two subnets in different AZs."
  }
}

variable "security_group_id" {
  description = "The rds security group, which accepts 5432 from the lambda and bastion groups only."
  type        = string
}

variable "engine_version" {
  description = <<-EOT
    Exact PostgreSQL version. Checked on account 725699850301 on 29 Aug 2026:
    RDS offers 16.9 through 16.15; 16.4 has been removed.

    16.10 is chosen because the local container image imresamu/postgis:16-3.5
    ships exactly PostgreSQL 16.10, so laptops and staging run the same engine.
  EOT
  type        = string
  default     = "16.10"
}

variable "instance_class" {
  description = "db.t4g.micro — Graviton, confirmed orderable in all three Sydney AZs on gp3."
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "GB of gp3. 20 is the RDS minimum, and far more than this dataset needs."
  type        = number
  default     = 20
}

variable "database_name" {
  description = "Initial database created inside the instance."
  type        = string
  default     = "sportable"
}

variable "master_username" {
  description = <<-EOT
    Master user. Not a superuser on RDS — it holds `rds_superuser`, which is
    what permits CREATE EXTENSION postgis. Avoid names RDS reserves, such as
    `rdsadmin`.
  EOT
  type        = string
  default     = "sportable_admin"
}

variable "ssm_prefix" {
  description = "SSM Parameter Store path prefix, e.g. \"/sportable/staging\"."
  type        = string
}

variable "backup_retention_days" {
  description = <<-EOT
    Automated backup retention, in days.

    Set to 1, not 7, because account 725699850301 is on the AWS **Free plan**
    and RDS rejects longer retention outright:

        FreeTierRestrictionError: The specified backup retention period exceeds
        the maximum available to free tier customers.

    This is a plan restriction, not a cost one — the storage would have been
    free either way. If the account is ever upgraded to a paid plan, 7 is the
    sensible value.

    If 1 is also rejected, 0 disables automated backups entirely. That is
    acceptable for staging, whose data is rebuildable by re-running ingestion,
    but it must not be carried into production.
  EOT
  type        = number
  default     = 1
}

variable "log_retention_days" {
  description = <<-EOT
    CloudWatch retention for exported PostgreSQL logs.

    This matters more than it looks: log groups default to NEVER EXPIRE, which
    quietly consumes the 5 GB free allowance and then bills forever.
  EOT
  type        = number
  default     = 14
}

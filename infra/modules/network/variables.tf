# ==============================================================================
# network module — inputs
# ==============================================================================
# A module knows nothing about "staging" or "prod". Everything environment-
# specific arrives through these variables, so the same code builds the
# Iteration 2 production VPC with different numbers and no edits.
# ==============================================================================

variable "name_prefix" {
  description = "Prefix for every resource name and Name tag, e.g. \"sportable-staging\"."
  type        = string
}

variable "vpc_cidr" {
  description = <<-EOT
    Address range for the whole VPC. A /16 gives ~65,000 addresses; we need
    dozens, but the size costs nothing and leaves room to grow.

    Verified free on account 725699850301 on 29 Aug 2026 — the only existing
    VPC is the default on 172.31.0.0/16.
  EOT
  type        = string

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be valid CIDR notation, e.g. 10.0.0.0/16."
  }
}

variable "azs" {
  description = <<-EOT
    Exactly two availability zones. RDS requires a DB subnet group spanning two
    AZs even for a single-AZ instance, so this is a hard requirement rather than
    a preference.

    Confirmed available for db.t4g.micro on gp3: ap-southeast-2a, 2b and 2c.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.azs) == 2
    error_message = "Provide exactly two AZs — RDS subnet groups require two, and a third would cost an unused subnet."
  }
}

variable "public_subnet_cidr" {
  description = "Public subnet, holds only the bastion. /24 is far larger than needed and keeps the maths obvious."
  type        = string
}

variable "private_subnet_cidrs" {
  description = <<-EOT
    Two private subnets, one per AZ, in the same order as `azs`.

    The first holds the Lambda ENIs and the RDS instance. The second is
    deliberately empty — it exists only so the DB subnet group spans two AZs.
    An empty subnet costs nothing.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_cidrs) == 2
    error_message = "Provide exactly two private subnet CIDRs, matching the two AZs."
  }
}

variable "allowed_ssh_cidrs" {
  description = <<-EOT
    Source ranges permitted to SSH to the bastion. Team members' public IPs,
    each as a /32.

    These are residential addresses and WILL change — after a router reboot, or
    whenever the ISP decides. Being locked out is expected at least once per
    iteration; the fix is to update this list and re-apply, never to widen the
    range to 0.0.0.0/0.
  EOT
  type        = list(string)

  validation {
    condition     = !contains(var.allowed_ssh_cidrs, "0.0.0.0/0")
    error_message = "0.0.0.0/0 exposes the bastion to the entire internet. Add specific /32 addresses instead."
  }
}

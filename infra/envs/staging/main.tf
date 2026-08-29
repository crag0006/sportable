# ==============================================================================
# staging environment
# ==============================================================================
# Modules are generic; this file supplies the concrete numbers. Iteration 2's
# production environment will call the same modules with different values.
# ==============================================================================

locals {
  name_prefix = "sportable-staging"

  # 2a and 2b. Verified 29 Aug 2026: all three Sydney AZs offer db.t4g.micro on
  # gp3, so this is a free choice rather than a constrained one.
  azs = ["ap-southeast-2a", "ap-southeast-2b"]
}

module "network" {
  source = "../../modules/network"

  name_prefix = local.name_prefix
  vpc_cidr    = "10.0.0.0/16"
  azs         = local.azs

  public_subnet_cidr = "10.0.0.0/24"

  # First entry is az-a: Lambda ENIs and the RDS instance.
  # Second is az-b and stays empty — it exists only so the DB subnet group
  # spans two availability zones, which RDS requires even for a single-AZ
  # instance. An empty subnet costs nothing.
  private_subnet_cidrs = ["10.0.1.0/24", "10.0.2.0/24"]

  allowed_ssh_cidrs = var.allowed_ssh_cidrs
}

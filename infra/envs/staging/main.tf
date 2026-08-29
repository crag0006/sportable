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

module "database" {
  source = "../../modules/database"

  name_prefix = local.name_prefix
  ssm_prefix  = "/sportable/staging"

  # Both private subnets: RDS needs a subnet group spanning two AZs even for a
  # single-AZ instance. The az-b subnet exists for exactly this.
  subnet_ids        = module.network.private_subnet_ids
  security_group_id = module.network.rds_security_group_id

  # Verified on this account 29 Aug 2026 — see the module variable comments.
  engine_version = "16.10"
  instance_class = "db.t4g.micro"
}

module "bastion" {
  source = "../../modules/bastion"

  name_prefix       = local.name_prefix
  subnet_id         = module.network.public_subnet_id
  security_group_id = module.network.bastion_security_group_id
  ssh_public_key    = var.ssh_public_key
}

module "static_site" {
  source = "../../modules/static_site"

  name_prefix = local.name_prefix
  account_id  = var.expected_account_id
}

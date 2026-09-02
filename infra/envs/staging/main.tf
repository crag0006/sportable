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

  # Routing the API through the same distribution is what removes CORS from the
  # problem entirely: the SPA and the API share one origin, so the browser never
  # makes a cross-origin request.
  api_origin_domain = module.api.api_domain
}

module "api" {
  source = "../../modules/api"

  name_prefix = local.name_prefix

  # Pre-built by the account holder. We hold iam:PassRole on it but cannot read
  # or change its policies — see the module's variable documentation.
  execution_role_arn = var.lambda_execution_role_arn

  # path.root is infra/envs/staging, so three levels up is the repository root.
  #
  # NOT backend/handlers/ any more. That directory holds source; this one holds
  # the BUILT package — the application plus its dependencies, installed for
  # Lambda's platform by backend/scripts/build_lambda.sh. The pipeline runs that
  # script before terraform; so must you, if you apply by hand.
  source_dir = "${path.root}/../../../backend/build/package"

  # az-a only: the RDS instance is there, and a second ENI would buy nothing.
  subnet_ids        = [module.network.private_subnet_ids[0]]
  security_group_id = module.network.lambda_security_group_id

  db_url_ssm_parameter = module.database.ssm_url_parameter

  # Same tree the app_config module writes to. The api module reads the search
  # parameters from it at APPLY time, so they must exist first — Terraform
  # cannot infer that from a path string.
  ssm_prefix = "/sportable/staging"

  depends_on = [module.app_config]
}

# ------------------------------------------------------------------------------
# T5 — configuration and observability
# ------------------------------------------------------------------------------

module "app_config" {
  source = "../../modules/app_config"

  name_prefix = local.name_prefix
  ssm_prefix  = "/sportable/staging"

  # AC1.2.4 names these three. Adding a fourth is a tfvars change and an apply —
  # no code change, no release.
  distance_bands_m   = [250, 500, 1000]
  default_distance_m = 500

  # Each threshold is longer than its publisher's cadence, so one missed refresh
  # does not make the UI apologise for data that is fine.
  #   vic_sport_rec, public_toilets_nptm, ptv_gtfs  publish weekly  -> 14 days
  #   osm                                           publishes monthly -> 45 days
  # Keys must match the extractor module names in data/ingestion/extractors/.
  source_staleness_days = {
    vic_sport_rec       = 14
    public_toilets_nptm = 14
    ptv_gtfs            = 14
    osm                 = 45
  }
}

module "observability" {
  source = "../../modules/observability"

  name_prefix  = local.name_prefix
  alert_emails = var.alert_emails

  function_name            = module.api.function_name
  function_timeout_seconds = module.api.function_timeout_seconds
  api_id                   = module.api.api_id
  db_instance_identifier   = module.database.instance_identifier
}

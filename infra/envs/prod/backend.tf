# ==============================================================================
# Remote state
# ==============================================================================
#
# Same bucket as every other environment, different key. The key is what isolates
# them: an apply here can never touch a staging or iteration resource, and an
# apply there can never touch production.
#
# FIRST RUN
#   terraform init
# ==============================================================================

terraform {
  backend "s3" {
    bucket       = "sportable-tfstate-725699850301"
    key          = "prod/terraform.tfstate"
    region       = "ap-southeast-2"
    encrypt      = true
    use_lockfile = true
  }
}

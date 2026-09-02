# ==============================================================================
# Remote state
# ==============================================================================
#
# Same bucket as staging, different key. The key is what isolates the two: this
# environment can be applied, or destroyed, without Terraform ever considering a
# staging resource.
#
# FIRST RUN
#   terraform init
# ==============================================================================

terraform {
  backend "s3" {
    bucket       = "sportable-tfstate-725699850301"
    key          = "iteration-1/terraform.tfstate"
    region       = "ap-southeast-2"
    encrypt      = true
    use_lockfile = true
  }
}

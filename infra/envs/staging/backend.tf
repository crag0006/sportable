# ==============================================================================
# Remote state
# ==============================================================================
#
# The bucket is created by infra/bootstrap, by hand, before this ever runs.
#
# use_lockfile = true replaces the DynamoDB table you will see in every older
# tutorial. DynamoDB never stored state — it was only a mutex, because S3 could
# not once express "create this object only if it does not already exist". S3
# gained conditional writes in 2024, so Terraform now writes a small lock object
# beside the state, and HashiCorp has marked `dynamodb_table` deprecated.
#
# FIRST RUN
#   terraform init
#
# The state key is namespaced by environment so prod can share the bucket later
# without any chance of collision.
# ==============================================================================

terraform {
  backend "s3" {
    bucket       = "sportable-tfstate-725699850301"
    key          = "staging/terraform.tfstate"
    region       = "ap-southeast-2"
    encrypt      = true
    use_lockfile = true
  }
}

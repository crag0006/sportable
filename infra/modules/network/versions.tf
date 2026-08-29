# A module declares the versions it is written against, separately from the
# environment that calls it. Terraform resolves one provider version for the
# whole run — this constraint says which versions this module is known to work
# with, and fails fast if an environment pins something incompatible.
terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }
}

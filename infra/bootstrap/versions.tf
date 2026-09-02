terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # NO backend block, deliberately.
  #
  # This configuration creates the bucket that every other configuration uses
  # for remote state. It cannot store its own state in a bucket that does not
  # exist yet, so it runs with local state and is applied by hand, once.
}

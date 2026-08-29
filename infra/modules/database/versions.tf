terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
    # Generates the master password. It is written straight to SSM and never
    # surfaced as a Terraform output — see main.tf.
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }
}

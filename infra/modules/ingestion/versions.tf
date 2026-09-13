# ==============================================================================
# ingestion module — provider requirements
# ==============================================================================
# Declared per-module, following the api module: a module states what it needs
# and the env root composes the constraints. archive is here because fetch.tf
# and load.tf zip their packages with data.archive_file.
# ==============================================================================

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }
}
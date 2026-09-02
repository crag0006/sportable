# ==============================================================================
# Terraform state backend — applied ONCE, by hand, with local state
# ==============================================================================
#
# WHY THIS IS SEPARATE FROM EVERYTHING ELSE
#   Terraform records what it built in a state file. That state has to live
#   somewhere both you and the deploy pipeline can read. S3 is that somewhere —
#   but a configuration cannot store its state in a bucket it has not created
#   yet. So this one bootstraps the rest, keeps its state locally, and is never
#   run by CI.
#
# HOW TO APPLY
#   cd infra/bootstrap
#   terraform init
#   terraform plan      # read it — expect ~5 to add, 0 to change, 0 to destroy
#   terraform apply
#
# AFTER THAT
#   Do not run it again. If you ever need to, it should report no changes.
# ==============================================================================

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "sportable"
      Environment = "shared"
      ManagedBy   = "terraform"
      Component   = "bootstrap"
    }
  }
}

variable "region" {
  description = "AWS region. Everything for this project lives in Sydney."
  type        = string
  default     = "ap-southeast-2"
}

variable "account_id" {
  description = <<-EOT
    Account id, used only to make the bucket name unique. S3 bucket names are
    globally unique across every AWS account on earth, so "sportable-tfstate"
    is almost certainly taken by a stranger.
  EOT
  type        = string
  default     = "725699850301"
}

# ------------------------------------------------------------------ the bucket
#
# The four checkov:skip lines below are deliberate, documented exceptions.
# Suppress a specific check with a reason, inside the resource — never turn on
# soft_fail in CI, which silences every finding at once.
#
# NOTE: checkov only honours these comments INSIDE the resource block. Placed
# above it they are ignored silently, which is how this was first written.
resource "aws_s3_bucket" "state" {
  # checkov:skip=CKV_AWS_18:Access logging needs a second bucket which itself
  #   needs logging. Disproportionate for a student project whose state bucket
  #   has two writers, and CloudTrail already records every API call.
  # checkov:skip=CKV_AWS_144:Cross-region replication is disaster recovery for
  #   irreplaceable data. This state is reproducible from the repository.
  # checkov:skip=CKV_AWS_145:AES256 (SSE-S3) rather than SSE-KMS. A customer
  #   managed key costs ~USD $1/month plus per-request charges and adds nothing
  #   here: no principal outside this account can read the bucket at all.
  # checkov:skip=CKV2_AWS_62:Nothing consumes state-change events.
  bucket = "sportable-tfstate-${var.account_id}"

  # Refuse to delete a bucket that still has objects in it. Losing state means
  # Terraform forgets every resource it manages — recoverable, but a bad day.
  lifecycle {
    prevent_destroy = true
  }
}

# Versioning is the safety net. A corrupted or truncated state file can be
# rolled back to the previous version, which has saved more projects than any
# other single S3 setting.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# All four of these default to false on a new bucket. Setting them explicitly
# means a future misconfiguration cannot quietly make state public.
resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning without expiry means every state write is kept forever. State files
# are small, but this keeps the bucket tidy and satisfies the lifecycle check.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

output "state_bucket" {
  description = "Put this in the backend block of every environment."
  value       = aws_s3_bucket.state.id
}

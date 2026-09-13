# ==============================================================================
# ingestion module — the raw zone and the quarantine bucket
# ==============================================================================
# The raw zone is an immutable, dated archive. Nothing edits an object once it
# lands; a re-fetch of changed data writes a new key under a new dt= partition.
# That is what makes a load reproducible months later: the transform can be
# re-run against the exact bytes the publisher served on the day.
#
# Two buckets, not one prefix, because they have different lifecycles and
# different audiences. Raw payloads age into Glacier and are read by machines.
# Quarantined rows stay hot and are read by a human deciding whether the
# transform is wrong or the publisher is.
# ==============================================================================

resource "aws_s3_bucket" "raw" {
  bucket = "${var.name_prefix}-raw-${var.account_id}"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-raw"
    Zone = "raw"
  })
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id

  versioning_configuration {
    status = "Enabled"
  }
}

# handler.py overwrites _manifests/<prefix>/latest.json on every run. Versioning
# is what keeps that file's history — without it, the record of what the
# previous run saw is destroyed by the next run.
resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket = aws_s3_bucket.raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# The transition keys off the object tag, not the prefix. handler.py writes
# Tagging="zone=raw" on payloads and writes no tag on manifests, so payloads age
# into Glacier Instant Retrieval while _manifests/ stays in Standard. Every run
# reads latest.json; that one should not be paying a retrieval price.
resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    id     = "payloads-to-glacier-ir"
    status = "Enabled"

    filter {
      tag {
        key   = "zone"
        value = "raw"
      }
    }

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }

  rule {
    id     = "expire-old-manifest-versions"
    status = "Enabled"

    filter {
      prefix = "_manifests/"
    }

    noncurrent_version_expiration {
      noncurrent_days = 180
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ------------------------------------------------------------------------------
# Quarantine
# ------------------------------------------------------------------------------
# A row that fails validation is not silently dropped and not loaded anyway. It
# is written here with the reason attached, so the coverage figures in the DMP
# can be reconciled against something concrete rather than asserted.

resource "aws_s3_bucket" "quarantine" {
  bucket = "${var.name_prefix}-quarantine-${var.account_id}"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-quarantine"
    Zone = "quarantine"
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id

  rule {
    id     = "expire-quarantine"
    status = "Enabled"

    filter {}

    expiration {
      days = 365
    }
  }
}

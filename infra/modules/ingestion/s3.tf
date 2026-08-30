# ==============================================================================
# Ingestion — the raw zone and the quarantine bucket
# ==============================================================================
#
# WHY A RAW ZONE AT ALL
#   The bytes a publisher sent are written down before anything interprets them.
#   When a transform turns out to be wrong in three weeks — and one will — the
#   fix is a re-run over data we already hold, not a re-fetch.
#
#   That distinction matters because these publishers OVERWRITE. Victoria's open
#   data portal serves one current file per dataset; there is no archive to ask
#   for last month's version. If we did not keep it, it is gone.
#
# WHY A SEPARATE QUARANTINE BUCKET
#   Rejected rows are not failures to be discarded, they are evidence. Keeping
#   them apart from the raw zone means "what did the publisher send" and "what
#   could we not use" are two questions with two answers, rather than one folder
#   somebody has to reason about.
#
#   Separate BUCKET rather than a prefix, because the load Lambda writes here
#   with different intent and a bucket boundary is the only one IAM can express
#   cheaply.
# ==============================================================================

resource "aws_s3_bucket" "raw" {
  bucket = "${var.name_prefix}-raw-${var.account_id}"

  # checkov:skip=CKV_AWS_145:AES256 rather than SSE-KMS. A customer managed key
  # costs ~USD $1/month plus per-request charges to encrypt open government data
  # that anyone can download from the publisher unencrypted.

  # checkov:skip=CKV_AWS_18:Access logging needs a second bucket that itself
  # cannot be logged, and every write here is already recorded by the Lambda's
  # own CloudWatch log group plus CloudTrail management events. On a student
  # project the extra bucket is cost and clutter for no new information.
  # checkov:skip=CKV_AWS_144:Cross-region replication doubles storage cost to
  # protect against a regional S3 failure. This data is re-fetchable from the
  # publishers on demand; the project ends in nine weeks.
  # checkov:skip=CKV2_AWS_62:Event notifications ARE configured — see the
  # aws_s3_bucket_notification in load.tf. Checkov does not associate a
  # notification declared in another file with this resource.

  tags = { Name = "${var.name_prefix}-raw" }
}

# Versioning is the point of the whole bucket. A publisher who changes a file
# under the same name must not be able to destroy what we already recorded, and
# a loader bug that overwrites a good object must be recoverable.
resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    apply_server_side_encryption_by_default {
      # AES256, not a customer-managed KMS key. Open government data is public
      # by definition; a CMK would cost ~USD $1/month plus per-request charges
      # to encrypt information anyone can download.
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Storage is the only part of ingestion that grows without bound, so it is the
# only part with a lifecycle rule.
resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    id     = "archive-then-expire"
    status = "Enabled"

    filter {}

    # Glacier Instant Retrieval, not Deep Archive: retrieval stays immediate, so
    # a re-run over archived data does not need a restore job and a wait. At
    # 90 days nothing is being actively reprocessed, but it may still be needed.
    transition {
      days          = var.archive_after_days
      storage_class = "GLACIER_IR"
    }

    # Old VERSIONS expire; current objects never do. Versioning without this is
    # how a bucket quietly accumulates every weekly fetch forever.
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiry_days
    }

    # A multipart upload that fails partway leaves parts that are billed but
    # invisible in the console. This is the single most common source of
    # unexplained S3 cost.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket" "quarantine" {
  bucket = "${var.name_prefix}-quarantine-${var.account_id}"

  # checkov:skip=CKV_AWS_145:AES256 rather than SSE-KMS. A customer managed key
  # costs ~USD $1/month plus per-request charges to encrypt open government data
  # that anyone can download from the publisher unencrypted.

  # checkov:skip=CKV_AWS_18:See the raw bucket — same reasoning.
  # checkov:skip=CKV_AWS_144:See the raw bucket — same reasoning.
  # checkov:skip=CKV2_AWS_61:Rejected rows are evidence, not waste. A lifecycle
  # rule that expired them would delete the record of what went wrong, which is
  # the only reason this bucket exists. Volume here is a tiny fraction of raw.
  # checkov:skip=CKV2_AWS_62:No notification wanted. Nothing should trigger
  # automatically off a rejection; a human decides what a bad row means.

  tags = { Name = "${var.name_prefix}-quarantine" }
}

resource "aws_s3_bucket_versioning" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id
  versioning_configuration {
    status = "Enabled"
  }
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
  bucket                  = aws_s3_bucket.quarantine.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

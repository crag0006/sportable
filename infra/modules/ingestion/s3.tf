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
  # checkov:skip=CKV_AWS_144:Cross-region replication doubles storage against a
  #   5 GB Free Tier allowance to protect an archive that can be re-fetched from
  #   the publisher. Reproducibility here comes from the manifest, not a replica.
  # checkov:skip=CKV_AWS_18:Access logging needs a second bucket and bills for
  #   the log objects. The raw zone is written by one function and read by one
  #   function, both of which log every object key to CloudWatch already.
  # checkov:skip=CKV2_AWS_62:Event notifications ARE configured — see the
  #   aws_s3_bucket_notification in load.tf.
  # checkov:skip=CKV_AWS_145:AES256 rather than SSE-KMS. A customer managed key
  #   costs ~USD $1/month plus per-request charges to encrypt Australian open
  #   data that the publisher serves unencrypted to anyone who asks. Encryption
  #   is configured — see aws_s3_bucket_server_side_encryption_configuration.

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

# ==============================================================================
# The quarantine bucket
# ==============================================================================
# WHY THIS IS IN S3 AND NOT ONLY IN POSTGRES
#
# There is already a `quarantine` table, and for a load that SUCCEEDS it is the
# better home: a human diagnosing a bad transform wants SQL, not object keys.
#
# The problem is the load that FAILS. write_quarantine() inserts inside the load
# transaction, check_rejection_rate() then raises LoadAbortedError above the
# threshold, and loader.connect() rolls the transaction back on any exception.
# So the rows are discarded at exactly the moment they become evidence — and the
# abort message tells the operator to "inspect the quarantine table before
# rerunning", which on that path would be empty.
#
# An S3 write is outside the database transaction and survives the rollback.
# The table keeps the successful loads; this bucket keeps the aborted ones.
#
# No event notification, deliberately. Nothing should react to a rejected row
# landing — the alarm in alarms.tf keys off the loader's log events instead, and
# a notification here would be a second trigger on the same failure.
# ==============================================================================

resource "aws_s3_bucket" "quarantine" {
  # checkov:skip=CKV_AWS_144:Cross-region replication to protect rejected rows
  #   that can be reproduced by re-running the transform against the raw zone,
  #   which is itself versioned. The evidence is derived, not primary.
  # checkov:skip=CKV_AWS_18:Access logging needs a second bucket and bills for
  #   the log objects. One writer, one human reader, both already logged.
  # checkov:skip=CKV_AWS_145:AES256 rather than SSE-KMS, matching the raw zone.
  #   A customer managed key costs ~USD $1/month to encrypt rows derived from
  #   Australian open data the publisher serves unencrypted to anyone.
  # checkov:skip=CKV2_AWS_62:Event notifications are deliberately absent — see
  #   the block comment above.

  bucket = "${var.name_prefix}-quarantine-${var.account_id}"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-quarantine"
    Zone = "quarantine"
  })
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
  bucket = aws_s3_bucket.quarantine.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Quarantined rows stay in Standard and are NOT aged into Glacier, unlike the
# raw zone. They are read by a person deciding whether the transform is wrong or
# the publisher is, and that decision happens in the days after the alarm, not
# in a year. Ninety days is long enough to cover an iteration boundary.
resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = aws_s3_bucket.quarantine.id

  rule {
    id     = "expire-old-quarantine"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
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

# ==============================================================================
# ingestion module — the Lambda artefact bucket
# ==============================================================================
# WHY THIS BUCKET EXISTS
#
# A Lambda handed its code with `filename` is a direct upload, and AWS caps a
# direct upload at 50 MB zipped. The load package is 48.8 MB — pandas and numpy
# are 117 MB of the 166 MB unzipped — so it ships at 97.6% of a hard limit that
# one added dependency would breach. `s3_bucket`/`s3_key` raises the ceiling to
# 250 MB zipped, so that is how the load function is shipped.
#
# fetch (0.9 MB) and derive (4.7 MB) stay on direct upload. Routing them through
# S3 would add an object and a round trip to buy headroom they do not need, and
# the asymmetry is the point: the mechanism follows the constraint.
#
# WHY NOT THE RAW BUCKET
#
# Because aws_s3_bucket_notification.raw in load.tf fires on ObjectCreated for
# `.zip` with NO prefix filter. Putting load.zip in the raw zone would wake the
# loader with its own deployment artefact as the payload, every deploy. A second
# bucket is cheaper than the prefix filter that would otherwise be load-bearing.
# ==============================================================================

resource "aws_s3_bucket" "artifacts" {
  # checkov:skip=CKV_AWS_144:Cross-region replication to protect an artefact that
  #   is rebuilt from source by every CI run. The build is the backup.
  # checkov:skip=CKV_AWS_18:Access logging needs a second bucket and bills for the
  #   log objects. Written by CI, read once by the Lambda service at deploy time.
  # checkov:skip=CKV_AWS_145:AES256 rather than SSE-KMS, matching the raw zone. A
  #   customer managed key costs ~USD $1/month to encrypt a zip of open-source
  #   wheels and this repository's own code, neither of which is a secret.
  # checkov:skip=CKV2_AWS_62:Event notifications are deliberately absent. Nothing
  #   should react to an artefact upload — that is the bug this bucket avoids.

  bucket = "${var.name_prefix}-artifacts-${var.account_id}"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-artifacts"
    Zone = "artifacts"
  })
}

# Keys are content-addressed, so a given key is written once and never changes.
# Versioning therefore accumulates nothing in normal operation; it is here so an
# accidental overwrite or delete is recoverable rather than final.
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Expiring an artefact does NOT break the function running on it: Lambda copies
# the code into its own storage at create and update time and never reads the
# object again. A published version keeps working after its zip has aged out,
# which is what makes `publish = true` the rollback mechanism rather than this
# bucket. Ninety days is generous for an object whose only other reader is a
# `terraform apply` that would rebuild it anyway.
resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "expire-superseded-artefacts"
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

# ------------------------------------------------------------------------------
# The load package
# ------------------------------------------------------------------------------
# The key carries the archive's SHA-1, which makes the object content-addressed:
# a code change writes a NEW key rather than overwriting the old one, so the
# function can never be pointed at a key whose contents changed underneath it.
# That ordering hazard is real with a static key — S3 is the source of truth at
# update time, and a same-apply overwrite is a race.
resource "aws_s3_object" "load" {
  # checkov:skip=CKV_AWS_186:Encrypted with the bucket's AES256 default. See the
  #   CKV_AWS_145 note above for why not SSE-KMS.

  bucket = aws_s3_bucket.artifacts.id
  key    = "lambda/load-${data.archive_file.load.output_sha}.zip"

  source = data.archive_file.load.output_path

  # Forces a re-upload when the zip changes. Without it Terraform compares only
  # metadata and a rebuilt package can be silently skipped.
  etag = data.archive_file.load.output_md5

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-load-package"
  })
}

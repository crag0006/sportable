# ==============================================================================
# Load — inside the VPC, triggered by the bucket rather than by a clock
# ==============================================================================
#
# THIS ONE HAS A vpc_config BLOCK, and its sibling in fetch.tf does not.
#
# That single difference is the whole architecture of ingestion:
#
#   fetch   outside the VPC   internet: yes   RDS: no    S3: over the public endpoint
#   load    inside  the VPC   internet: no    RDS: yes   S3: over the gateway endpoint
#
# Neither needs a NAT Gateway, which is what keeps ingestion free to run.
#
# WHY AN S3 NOTIFICATION AND NOT A SECOND SCHEDULE
#   The fetch step does not need to know this function exists. Anything that
#   lands in the raw zone is processed — including a file someone uploads by
#   hand, which is exactly what makes the manual fallback in the runbook work
#   without special-casing.
# ==============================================================================

data "archive_file" "load" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${var.name_prefix}-load.zip"
  excludes    = ["notebooks", "tests", ".venv", "__pycache__", "uv.lock", "pyproject.toml"]
}

resource "aws_cloudwatch_log_group" "load" {
  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems. This is a nine-week student project; 12
  #   months would outlive it while consuming the 5 GB CloudWatch free
  #   allowance.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month to
  #   encrypt logs about public open data that are already encrypted at rest
  #   with the CloudWatch service key.
  name              = "/aws/lambda/${var.name_prefix}-load"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.name_prefix}-load-logs" }
}

resource "aws_lambda_function" "load" {
  function_name = "${var.name_prefix}-load"
  description   = "Reads a landed raw object, records a manifest, and will load rows once the Data team's loaders exist."

  role    = var.execution_role_arn
  handler = "ingestion.load.handler"
  runtime = var.runtime

  filename         = data.archive_file.load.output_path
  source_code_hash = data.archive_file.load.output_base64sha256

  # More memory than fetch, and it is not really about memory: Lambda scales CPU
  # with memory, and this function parses files. More importantly it will hold a
  # GTFS archive in memory once the real loaders land.
  memory_size = var.load_memory_mb
  timeout     = var.load_timeout_seconds

  # checkov:skip=CKV_AWS_50:X-Ray tracing needs xray:PutTraceSegments on the
  #   execution role, which is pre-built by the account holder and cannot be
  #   read or changed here.
  # checkov:skip=CKV_AWS_116:Asynchronous, so a DLQ would catch something — but
  #   the object that triggered this function is still in the versioned raw
  #   bucket. Replaying is a re-invoke or a re-upload, and the load-failures
  #   alarm says when that is needed. A DLQ would add a queue nobody reads.
  # checkov:skip=CKV_AWS_173:Environment variables are a bucket name and a
  # database URL that is already a SecureString in Parameter Store. Adding a CMK
  # here would cost ~USD $1/month to re-encrypt a value AWS already encrypts.
  # checkov:skip=CKV_AWS_272:Code signing needs a signing profile and a CI
  # signing step; the deployment path already uses OIDC with no static keys.
  # checkov:skip=CKV_AWS_115:Reserved concurrency cannot be set on this account
  # — the total limit is 10 and the Free plan refuses to raise it.

  vpc_config {
    # az-a only, matching the API function and the RDS instance. A second ENI in
    # az-b would buy nothing and this account's ENI quota is not generous.
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      RAW_BUCKET        = aws_s3_bucket.raw.id
      QUARANTINE_BUCKET = aws_s3_bucket.quarantine.id
      # Present so the loader can connect the moment it exists. Read at apply
      # time from Parameter Store by the runner, exactly as the API does — this
      # function cannot reach SSM itself, for the same reason it cannot reach
      # the internet.
      DATABASE_URL = var.database_url
      ENVIRONMENT  = var.environment
      LOG_LEVEL    = "INFO"
    }
  }

  tags       = { Name = "${var.name_prefix}-load" }
  depends_on = [aws_cloudwatch_log_group.load]
}

# S3 needs permission on the FUNCTION before the notification can be created.
# Terraform infers that ordering from this reference; without the permission
# existing first, the notification below fails with an unhelpful
# "Unable to validate the following destination configurations".
resource "aws_lambda_permission" "s3" {
  statement_id  = "AllowFromRawBucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.load.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.raw.arn

  # Without this, any bucket in any account could invoke this function by
  # claiming to be S3.
  source_account = var.account_id
}

# One notification per dataset prefix, rather than one for the whole bucket.
#
# WHY. This function writes its manifests back into the bucket it is watching.
# A bucket-wide notification therefore invokes it again for every manifest —
# the handler's `_manifests/` guard stops the recursion, but only after paying
# for a cold start to discover there is nothing to do.
#
# S3 notification filters can only INCLUDE a prefix, never exclude one, so the
# fix is to name the prefixes we do want. The dataset names are already known
# here: they are the keys of the source registry.
#
# The handler keeps its guard anyway. Two mechanisms for a runaway loop is the
# right number when one of them is a configuration that someone might widen
# later without thinking about it.
resource "aws_s3_bucket_notification" "raw" {
  bucket = aws_s3_bucket.raw.id

  dynamic "lambda_function" {
    for_each = var.sources

    content {
      id                  = "load-${lambda_function.key}"
      lambda_function_arn = aws_lambda_function.load.arn
      events              = ["s3:ObjectCreated:*"]
      filter_prefix       = "${lambda_function.key}/"
    }
  }

  depends_on = [aws_lambda_permission.s3]
}

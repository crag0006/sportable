# ==============================================================================
# ingestion module — stages 2 and 3, transform/load and derive
# ==============================================================================
# Both run INSIDE the VPC because both talk to RDS, which has no public route.
# They reach S3 over the gateway VPC endpoint the network module already
# created, so being inside the VPC costs them nothing in reachability.
#
# The trigger is s3:ObjectCreated, not a second schedule. A schedule would have
# to guess how long the fetch takes and would fire on days when nothing changed:
# handler.py answers 304 or an identical hash by writing a manifest and NOT
# writing an object, so no event fires and no load runs. The pipeline does
# nothing on a quiet week without anyone arranging for it to do nothing.
# ==============================================================================

# The connection string, read on the CI runner at apply time. See the
# environment blocks below for why it is not read at runtime.
data "aws_ssm_parameter" "db_url" {
  name = var.ssm_db_url_parameter
}

data "archive_file" "load" {
  type        = "zip"
  source_dir  = var.load_source_dir
  output_path = "${path.module}/.build/load.zip"
}

resource "aws_lambda_function" "load" {
  # checkov:skip=CKV_AWS_272:Code signing requires an AWS Signer profile and a
  #   signing step in the pipeline. Disproportionate for a nine-week project.
  # checkov:skip=CKV_AWS_173:Environment variables are encrypted at rest with the
  #   AWS-managed Lambda key. A customer managed key adds ~USD $1/month and does
  #   not change who can read the configuration. The database URL IS here, as a
  #   value rather than a parameter name: see the environment block below.
  # checkov:skip=CKV_AWS_115:Reserved concurrency cannot be set on this account.
  #   Its total Lambda concurrency limit is 10 and AWS rejects a reservation
  #   against a limit that low. See the api module for the same constraint.
  # checkov:skip=CKV_AWS_50:X-Ray tracing needs xray:PutTraceSegments on the
  #   execution role. That role is pre-built by the account holder and this
  #   account cannot create or amend IAM policies.
  # checkov:skip=CKV_AWS_116:A dead letter queue needs sqs:SendMessage on the
  #   execution role. The role is pre-built and this account cannot amend IAM
  #   policies, so a DLQ would be configured and then silently fail to deliver.
  #   Failures are caught by the Errors alarm in alarms.tf instead. Revisit if
  #   the role gains SQS permissions.

  function_name = "${var.name_prefix}-load"
  description   = "Stage 2: validate, transform and upsert a raw object into the database."

  role          = var.execution_role_arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  # An immutable version per apply, matching the api module. A batch function
  # has no alias to move, but the version is what makes "put the old code back"
  # a one-call operation rather than a revert-and-redeploy.
  publish = true

  # Shipped through S3, not as a direct upload: at 48.8 MB zipped this package
  # sits at 97.6% of Lambda's 50 MB direct-upload cap. See artifacts.tf.
  #
  # source_code_hash is still the archive's hash, not the object's. It is what
  # tells Terraform the code changed and a new version must be published; the
  # S3 key changing is what tells Lambda where to read it from.
  s3_bucket        = aws_s3_object.load.bucket
  s3_key           = aws_s3_object.load.key
  source_code_hash = data.archive_file.load.output_base64sha256

  timeout     = 900
  memory_size = var.load_memory_mb

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      RAW_BUCKET = aws_s3_bucket.raw.id

      # Rejected rows are written here BEFORE the rejection-rate check, so the
      # evidence survives the transaction rollback that an aborted load causes.
      # See the block comment in s3.tf.
      QUARANTINE_BUCKET = aws_s3_bucket.quarantine.id

      # Read from SSM HERE, on the runner, and passed in. It was the parameter
      # NAME until the loader timed out reaching the SSM API: these functions
      # sit in a private subnet whose only route out is the S3 gateway
      # endpoint, so the call hangs rather than failing. An SSM interface
      # endpoint costs ~USD $7.30/month per AZ, which T5 already refused for
      # the API's own DATABASE_URL. Same trade, same answer.
      #
      # The value is in Terraform state either way: the RDS module generates
      # the password, so state is already sensitive and already encrypted.
      DATABASE_URL = data.aws_ssm_parameter.db_url.value

      REGISTER_DIR = "/var/task/sources"
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-load" })

  depends_on = [aws_cloudwatch_log_group.load]
}

resource "aws_cloudwatch_log_group" "load" {
  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems, not a nine-week student staging environment.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month to
  #   encrypt logs already encrypted at rest with the CloudWatch service key.

  name              = "/aws/lambda/${var.name_prefix}-load"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

resource "aws_lambda_permission" "load_from_s3" {
  statement_id   = "AllowExecutionFromS3"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.load.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.raw.arn
  source_account = var.account_id
}

resource "aws_s3_bucket_notification" "raw" {
  bucket = aws_s3_bucket.raw.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.load.arn
    events              = ["s3:ObjectCreated:*"]

    # Without this filter the notification is recursive in spirit if not in
    # fact: write_manifest() puts two objects under _manifests/ on every run,
    # including runs that landed nothing, and each would wake the loader for a
    # file it has no transformer for.
    filter_suffix = ".json"
  }

  # Payloads. The suffixes are the retrieval formats the source cards declare.
  lambda_function {
    lambda_function_arn = aws_lambda_function.load.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".csv"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.load.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".zip"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.load.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".xlsx"
  }

  depends_on = [aws_lambda_permission.load_from_s3]
}

# ------------------------------------------------------------------------------
# Stage 3 — derive
# ------------------------------------------------------------------------------
# Separate from the load because it is not per-object. The spatial join that
# decides a venue's toilet status depends on every amenity source having landed,
# so running it inside the loader would compute a status from a half-loaded
# table and then compute it again, differently, an hour later.
#
# Invoked by the loader when a load run completes, not by S3 and not by a
# schedule. It refreshes the materialised views at the end, which is what makes
# the new data visible to the API.

data "archive_file" "derive" {
  type        = "zip"
  source_dir  = var.derive_source_dir
  output_path = "${path.module}/.build/derive.zip"
}

resource "aws_lambda_function" "derive" {
  # checkov:skip=CKV_AWS_272:Code signing requires an AWS Signer profile and a
  #   signing step in the pipeline. Disproportionate for a nine-week project.
  # checkov:skip=CKV_AWS_173:Environment variables are encrypted at rest with the
  #   AWS-managed Lambda key. A customer managed key adds ~USD $1/month and does
  #   not change who can read the configuration. The database URL IS here, as a
  #   value rather than a parameter name: see the environment block below.
  # checkov:skip=CKV_AWS_115:Reserved concurrency cannot be set on this account.
  #   Its total Lambda concurrency limit is 10 and AWS rejects a reservation
  #   against a limit that low. See the api module for the same constraint.
  # checkov:skip=CKV_AWS_50:X-Ray tracing needs xray:PutTraceSegments on the
  #   execution role. That role is pre-built by the account holder and this
  #   account cannot create or amend IAM policies.
  # checkov:skip=CKV_AWS_116:A dead letter queue needs sqs:SendMessage on the
  #   execution role. The role is pre-built and this account cannot amend IAM
  #   policies, so a DLQ would be configured and then silently fail to deliver.
  #   Failures are caught by the Errors alarm in alarms.tf instead. Revisit if
  #   the role gains SQS permissions.

  function_name = "${var.name_prefix}-status-builder"
  description   = "Stage 3: derive venue_amenity_status and access chains, then refresh the read model."

  role          = var.execution_role_arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]

  # An immutable version per apply, matching the api module. A batch function
  # has no alias to move, but the version is what makes "put the old code back"
  # a one-call operation rather than a revert-and-redeploy.
  publish = true

  filename         = data.archive_file.derive.output_path
  source_code_hash = data.archive_file.derive.output_base64sha256

  timeout     = 900
  memory_size = var.load_memory_mb

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      # As above: resolved at apply time, because this function cannot reach
      # the SSM API from its subnet either.
      DATABASE_URL = data.aws_ssm_parameter.db_url.value
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-status-builder" })

  depends_on = [aws_cloudwatch_log_group.derive]
}

resource "aws_cloudwatch_log_group" "derive" {
  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems, not a nine-week student staging environment.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month to
  #   encrypt logs already encrypted at rest with the CloudWatch service key.

  name              = "/aws/lambda/${var.name_prefix}-status-builder"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

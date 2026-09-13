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

data "archive_file" "load" {
  type        = "zip"
  source_dir  = var.load_source_dir
  output_path = "${path.module}/.build/load.zip"
}

resource "aws_lambda_function" "load" {
  function_name = "${var.name_prefix}-load"
  description   = "Stage 2: validate, transform and upsert a raw object into the database."

  role    = var.execution_role_arn
  handler = "handler.handler"
  runtime = "python3.12"

  filename         = data.archive_file.load.output_path
  source_code_hash = data.archive_file.load.output_base64sha256

  timeout     = 900
  memory_size = var.load_memory_mb

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = {
      RAW_BUCKET        = aws_s3_bucket.raw.id
      QUARANTINE_BUCKET = aws_s3_bucket.quarantine.id

      # The parameter NAME. The function resolves it at runtime through the SSM
      # API, so the connection string never enters Terraform state, a plan
      # output or a CI log.
      SSM_DB_URL_PARAM = var.ssm_db_url_parameter

      REGISTER_DIR = "/var/task/sources"

      # The loader invokes the status builder asynchronously once a load has
      # committed. Passed as a name rather than looked up at runtime so the
      # dependency is visible in the plan.
      DERIVE_FUNCTION = "${var.name_prefix}-status-builder"
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-load" })

  depends_on = [aws_cloudwatch_log_group.load]
}

resource "aws_cloudwatch_log_group" "load" {
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
  function_name = "${var.name_prefix}-status-builder"
  description   = "Stage 3: derive venue_amenity_status and access chains, then refresh the read model."

  role    = var.execution_role_arn
  handler = "handler.handler"
  runtime = "python3.12"

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
      SSM_DB_URL_PARAM = var.ssm_db_url_parameter
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-status-builder" })

  depends_on = [aws_cloudwatch_log_group.derive]
}

resource "aws_cloudwatch_log_group" "derive" {
  name              = "/aws/lambda/${var.name_prefix}-status-builder"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

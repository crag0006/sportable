# ==============================================================================
# Access Assistant — I3 (function), I5 (route), I7 (throttle)
# ==============================================================================
# A SECOND FUNCTION, NOT A SECOND PACKAGE
#   The assistant reuses the archive built for the API. That package already
#   carries app/ — the repository layer it needs to read venues and events —
#   and every dependency. Pointing a second function at the same zip with a
#   different handler keeps the two in lockstep and costs one line in
#   backend/scripts/build_lambda.sh.
#
# WHY A SEPARATE FUNCTION AT ALL
#   Three reasons, all of them about blast radius:
#     - a Bedrock timeout must not take venue search down with it;
#     - the two need very different throttles, because one costs money per
#       call and the other does not;
#     - the assistant will want more memory and a longer timeout than a
#       database read, and sizing them together means over-paying for both.
#
# OFF BY DEFAULT
#   prod and iteration-1 call this module and neither runs an assistant.
# ==============================================================================

# TEMPORARY Bedrock credentials from another account. See the variable.
data "aws_ssm_parameter" "bedrock_bridge" {
  for_each = var.enable_assistant && var.bedrock_bridge_ssm_prefix != "" ? toset(["access_key_id", "secret_access_key"]) : toset([])

  name = "${var.bedrock_bridge_ssm_prefix}/${each.key}"
}

locals {
  bedrock_bridge_env = length(data.aws_ssm_parameter.bedrock_bridge) == 0 ? {} : {
    BEDROCK_ACCESS_KEY_ID     = data.aws_ssm_parameter.bedrock_bridge["access_key_id"].value
    BEDROCK_SECRET_ACCESS_KEY = data.aws_ssm_parameter.bedrock_bridge["secret_access_key"].value
  }
}

resource "aws_cloudwatch_log_group" "assistant" {
  count = var.enable_assistant ? 1 : 0

  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems, not a nine-week student project.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month and
  #   does not change who can read these logs. They contain counts and
  #   categories only — never a user's question. See handlers/assistant.py.
  name              = "/aws/lambda/${var.name_prefix}-assistant"
  retention_in_days = var.log_retention_days

  tags = { Name = "${var.name_prefix}-assistant-logs" }
}

resource "aws_lambda_function" "assistant" {
  count = var.enable_assistant ? 1 : 0

  # checkov:skip=CKV_AWS_272:Code signing needs an AWS Signer profile and a
  #   signing step in the pipeline. Disproportionate for a nine-week project.
  # checkov:skip=CKV_AWS_173:Environment variables are encrypted at rest with
  #   the AWS-managed Lambda key. A customer managed key adds ~USD $1/month and
  #   does not change who can read the configuration.
  # checkov:skip=CKV_AWS_115:Reserved concurrency cannot be set on this
  #   account. Its total Lambda concurrency limit is 10 and AWS rejects a
  #   reservation against a limit that low. The route throttle below is the
  #   cost control instead.
  # checkov:skip=CKV_AWS_50:X-Ray tracing needs xray:PutTraceSegments on the
  #   execution role, which is pre-built by the account holder and cannot be
  #   amended from here.
  # checkov:skip=CKV_AWS_116:A dead letter queue needs sqs:SendMessage on that
  #   same role. Failures are caught by the Errors alarm instead.
  function_name = "${var.name_prefix}-assistant"
  description   = "Access Assistant (Epic 6). Capability message only until intent handling lands."
  role          = var.execution_role_arn

  handler = "assistant.handler"
  runtime = var.runtime

  # The same archive the API uses, different entry point.
  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  memory_size = var.assistant_memory_mb
  timeout     = var.assistant_timeout_seconds

  publish = true

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [var.security_group_id]
  }

  environment {
    variables = merge(local.bedrock_bridge_env, {
      DATABASE_URL = data.aws_ssm_parameter.db_url.value
      ENVIRONMENT  = "staging"
      LOG_LEVEL    = "INFO"

      # Model ids as configuration, not constants in code. Changing model is
      # then a pipeline run rather than a pull request, and the id that was
      # actually used is visible in the function configuration.
      BEDROCK_TEXT_MODEL_ID      = var.bedrock_text_model_id
      BEDROCK_EMBEDDING_MODEL_ID = var.bedrock_embedding_model_id

      # Tunables in one JSON blob, the same shape as SEARCH_CONFIG: top-k, the
      # relevance floor, token ceilings and the daily cap. Resolved at apply
      # time so a threshold can change without editing Python.
      ASSISTANT_CONFIG = jsonencode(var.assistant_config)
    })
  }

  tags = { Name = "${var.name_prefix}-assistant" }

  depends_on = [aws_cloudwatch_log_group.assistant]
}

# API Gateway integrates with the alias, never the function, so a rollback has
# something to move. Same reasoning as the API's own alias.
resource "aws_lambda_alias" "assistant_live" {
  count = var.enable_assistant ? 1 : 0

  name             = "live"
  description      = "The assistant version currently serving traffic."
  function_name    = aws_lambda_function.assistant[0].function_name
  function_version = aws_lambda_function.assistant[0].version
}

resource "aws_apigatewayv2_integration" "assistant" {
  count = var.enable_assistant ? 1 : 0

  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.assistant_live[0].invoke_arn
  payload_format_version = "2.0"

  # Longer than the API's: a model call is slower than a database read. Still
  # below the function timeout so the function, not the gateway, decides.
  timeout_milliseconds = var.assistant_integration_timeout_ms
}

# A specific route, which takes precedence over the $default route that sends
# everything else to the API function.
resource "aws_apigatewayv2_route" "assistant" {
  count = var.enable_assistant ? 1 : 0

  # checkov:skip=CKV_AWS_309:Public by design, for the same reason as the
  #   $default route above: the product has no accounts, and asking the people
  #   it exists for to sign in would be a barrier. The check cannot express an
  #   authorization type of NONE being the correct answer.
  #
  #   This route is different from $default in one way that matters, so the
  #   compensating control is different too. Every request here can invoke a
  #   model, so abuse costs money rather than just capacity. It is capped at
  #   its own throttle — see route_settings in gateway.tf, 2 rps against the
  #   stage default of 50 — and out-of-scope questions are refused without any
  #   model call at all, so the cheapest path is also the most common one.
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST ${var.assistant_route_path}"
  target    = "integrations/${aws_apigatewayv2_integration.assistant[0].id}"
}

# A resource policy on the function, not an IAM policy — this account's
# principals cannot create IAM policies but can attach resource policies to
# resources they own. source_arn scopes it to this API.
resource "aws_lambda_permission" "assistant_apigw" {
  count = var.enable_assistant ? 1 : 0

  statement_id  = "AllowInvokeFromApiGatewayAssistant"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.assistant[0].function_name
  qualifier     = aws_lambda_alias.assistant_live[0].name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

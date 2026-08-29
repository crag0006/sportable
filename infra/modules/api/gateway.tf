# ==============================================================================
# API Gateway HTTP API in front of the Lambda alias
# ==============================================================================
#
# WHY HTTP API AND NOT REST API
#   AWS has two products with unhelpfully similar names. HTTP API is roughly a
#   third of the price (~$1.00 vs ~$3.50 per million requests), lower latency,
#   and simpler. REST API's extra features — request validation, API keys,
#   usage plans, native WAF — are things this project does not use.
#
#   In Terraform that means `aws_apigatewayv2_*`, NOT `aws_api_gateway_*`.
#   Mixing the two is the most common copy-paste error in this area.
#
# WHY A $default ROUTE RATHER THAN EXPLICIT ROUTES
#   The real handler will be FastAPI behind Mangum, which does its own routing.
#   Forwarding everything and letting the application decide keeps one source of
#   truth for the URL structure — add an endpoint in FastAPI and it works, with
#   no Terraform change.
#
#   Specific routes still win over $default, which is what makes Step 5's mock
#   responses possible: a mock on GET /api/v1/venues/search takes precedence,
#   and everything else continues to the Lambda.
#
# WHY THE INTEGRATION POINTS AT THE ALIAS
#   Pointing it at the function means every request runs $LATEST, and a rollback
#   has nothing to move. The alias is the whole rollback mechanism.
# ==============================================================================

resource "aws_apigatewayv2_api" "this" {
  # checkov:skip=CKV2_AWS_29:AWS WAF in front of API Gateway costs ~USD $5/month
  #   plus per-rule and per-request charges, to protect a read-only API over
  #   public open data with no authentication and no write path. The account's
  #   Lambda concurrency limit of 10 already bounds the blast radius of abuse.
  name          = "${var.name_prefix}-api"
  description   = "SportAble HTTP API. Fronted by CloudFront at /api/*."
  protocol_type = "HTTP"

  # CORS is deliberately NOT configured. The browser reaches this API through
  # CloudFront on the same origin as the SPA, so no request is ever
  # cross-origin. Configuring CORS here would be dead configuration that
  # quietly becomes wrong.

  tags = { Name = "${var.name_prefix}-api" }
}

# --------------------------------------------------------------- access logs
# Created explicitly so retention is ours. API Gateway will happily write to a
# group that never expires otherwise.
resource "aws_cloudwatch_log_group" "gateway" {
  # checkov:skip=CKV_AWS_338:A year of retention is a compliance rule for
  #   regulated production systems, not a nine-week student staging environment.
  # checkov:skip=CKV_AWS_158:A customer managed KMS key costs ~USD $1/month to
  #   encrypt access logs already encrypted with the CloudWatch service key.
  name              = "/aws/apigateway/${var.name_prefix}-api"
  retention_in_days = var.log_retention_days

  tags = { Name = "${var.name_prefix}-api-access-logs" }
}

# --------------------------------------------------------------- integration
resource "aws_apigatewayv2_integration" "lambda" {
  api_id           = aws_apigatewayv2_api.this.id
  integration_type = "AWS_PROXY"

  # The ALIAS, not the function. See the header comment.
  integration_uri = aws_lambda_alias.live.arn

  # Payload format 2.0 is the HTTP API default and what Mangum expects. Version
  # 1.0 exists for REST API compatibility and would change the event shape the
  # handler receives.
  payload_format_version = "2.0"

  integration_method   = "POST" # how API Gateway calls Lambda, not the client's method
  timeout_milliseconds = var.integration_timeout_ms
}

resource "aws_apigatewayv2_route" "default" {
  # checkov:skip=CKV_AWS_309:The route DOES specify an authorization type — NONE
  #   — and that is the correct value. This API serves public open data about
  #   venue accessibility to users who are never asked to sign in; requiring
  #   authentication would be a barrier to the people the product exists for.
  #   The check wants some auth mechanism present and cannot express "public by
  #   design". Abuse is bounded by stage throttling and by the account's Lambda
  #   concurrency ceiling of 10.
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"

  # Stated explicitly rather than left to default. This API is deliberately
  # public: it serves venue and accessibility data drawn from public open data,
  # to users who are not asked to sign in. Adding authentication would be a
  # barrier to exactly the people the product exists for.
  #
  # Rate limiting on the stage, and the account's Lambda concurrency ceiling of
  # 10, are what bound abuse instead.
  authorization_type = "NONE"
}

# ---------------------------------------------------------------------- stage
# The $default stage serves from the API's root URL with no stage name in the
# path — so https://<api-id>.execute-api.<region>.amazonaws.com/api/v1/health
# rather than .../prod/api/v1/health. That keeps the path identical whether a
# request arrives directly or through CloudFront.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.gateway.arn

    # JSON so the logs are queryable in CloudWatch Logs Insights rather than
    # being parsed by eye. integrationErrorMessage is the field that tells you
    # why a 502 happened, and it is the one people forget to include.
    format = jsonencode({
      requestId               = "$context.requestId"
      ip                      = "$context.identity.sourceIp"
      requestTime             = "$context.requestTime"
      httpMethod              = "$context.httpMethod"
      routeKey                = "$context.routeKey"
      path                    = "$context.path"
      status                  = "$context.status"
      protocol                = "$context.protocol"
      responseLength          = "$context.responseLength"
      responseLatency         = "$context.responseLatency"
      integrationStatus       = "$context.integrationStatus"
      integrationErrorMessage = "$context.integrationErrorMessage"
    })
  }

  default_route_settings {
    # Explicit rather than the 10,000 rps default. The account's Lambda
    # concurrency limit is 10, so anything above this would be absorbed by
    # Lambda throttling instead — better to reject at the edge, where the
    # response is fast and the access log records it.
    throttling_rate_limit  = var.throttle_rate_limit
    throttling_burst_limit = var.throttle_burst_limit
  }

  tags = { Name = "${var.name_prefix}-api-stage" }
}

# ----------------------------------------------------------------- permission
# A RESOURCE policy on the Lambda, not an IAM policy — which matters here,
# because this account's principals cannot create IAM policies but can attach
# resource policies to resources they own.
#
# source_arn scopes it to this API. Without that, any API Gateway in any account
# could invoke the function.
resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  qualifier     = aws_lambda_alias.live.name # the alias, again
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

variable "name_prefix" {
  description = "Prefix for resource names, e.g. \"sportable-staging\"."
  type        = string
}

variable "execution_role_arn" {
  description = <<-EOT
    ARN of the Lambda execution role.

    Passed in as a literal ARN rather than looked up with a data source, and
    NOT created here, because this account's principals cannot create IAM roles.
    The account holder pre-built `sportable-lambda-api`; we hold iam:PassRole on
    it but cannot read or change its policies.

    A Lambda attached to a VPC needs this role to allow
    ec2:CreateNetworkInterface, ec2:DescribeNetworkInterfaces and
    ec2:DeleteNetworkInterface — the AWS-managed AWSLambdaVPCAccessExecutionRole.
    We cannot verify that from here, but Lambda validates it at CREATION time
    and fails clearly:

        InvalidParameterValueException: The provided execution role does not
        have permissions to call CreateNetworkInterface on EC2

    So the first apply is the test.
  EOT
  type        = string
}

variable "source_dir" {
  description = "Directory to zip as the deployment package. Its files land at the root of the archive."
  type        = string
}

variable "handler" {
  description = <<-EOT
    Entry point, as `module.function`. The module name is the .py file at the
    ROOT of the zip — so `api.handler` means api.py, not handlers/api.py.

    `api.handler` is Mangum wrapping the FastAPI application. It replaced
    `stub.handler`, which served fixtures and needed no dependencies; the real
    application needs its dependencies installed into the package first. See
    the archive_file in main.tf.
  EOT
  type        = string
  default     = "api.handler"
}

variable "runtime" {
  type    = string
  default = "python3.12"
}

variable "memory_mb" {
  description = <<-EOT
    Lambda allocates CPU in proportion to memory, so this is a speed dial as
    much as a memory one. 512 MB is a reasonable starting point for a FastAPI
    handler doing a spatial query; measure before changing it.
  EOT
  type        = number
  default     = 512
}

variable "timeout_seconds" {
  description = <<-EOT
    10 seconds. API Gateway's own hard limit is 30, and a venue search that
    takes longer than a few seconds is broken rather than slow — failing fast
    surfaces that instead of hiding it.
  EOT
  type        = number
  default     = 10
}

variable "reserved_concurrency" {
  description = <<-EOT
    Caps simultaneous executions for this one function. -1 means no cap.

    **-1 is not a preference here, it is forced.** This account's TOTAL Lambda
    concurrency limit is 10 — a Free plan restriction; a normal account gets
    1000. AWS refuses to let a reservation drop the account's unreserved pool
    below 10, so reserving anything at all is impossible:

        InvalidParameterValueException: Specified ReservedConcurrentExecutions
        for function decreases account's UnreservedConcurrentExecution below
        its minimum value of [10].

    Check the quota with:
        aws lambda get-account-settings --query 'AccountLimit.ConcurrentExecutions'

    The upside: the account-wide limit of 10 already does what a per-function
    reservation would have done. A runaway loop cannot exceed ten concurrent
    executions, which is the cost guard we wanted.

    The downside is real and worth knowing before the demo: more than 10
    simultaneous requests will be throttled with a 429.
  EOT
  type        = number
  default     = -1
}

variable "subnet_ids" {
  description = "Private subnet(s) for the Lambda ENI. One is enough; the database lives in az-a."
  type        = list(string)
}

variable "security_group_id" {
  description = "T1's lambda security group: no ingress, egress to RDS and S3 only."
  type        = string
}

variable "db_url_ssm_parameter" {
  description = <<-EOT
    SSM parameter holding the database connection string.

    Terraform reads it and passes the VALUE as an environment variable, rather
    than the function reading SSM at runtime. That is a deliberate Iteration 1
    compromise: an in-VPC Lambda has no route to SSM, and interface VPC
    endpoints for ssm + kms cost roughly USD $14/month.

    The consequence is that the connection string is visible in the Lambda's
    configuration to anyone who can read it, and is stored in Terraform state.
    Recorded as a known compromise; revisit in Iteration 2.
  EOT
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch retention. Log groups default to NEVER EXPIRE, which quietly consumes the free allowance."
  type        = number
  default     = 14
}

variable "integration_timeout_ms" {
  description = <<-EOT
    How long API Gateway waits for Lambda. Must exceed the Lambda's own timeout
    or the client sees a 504 while the function is still running and being
    billed. Lambda is 10 s, so 15 s leaves headroom.

    API Gateway's own hard ceiling is 30 s and cannot be raised.
  EOT
  type        = number
  default     = 15000
}

variable "throttle_rate_limit" {
  description = <<-EOT
    Steady-state requests per second, across the whole API.

    Set explicitly rather than left at API Gateway's 10,000 default. This
    account's Lambda concurrency limit is 10, so traffic beyond a modest rate
    would be absorbed by Lambda throttling anyway — better to reject it at the
    edge, where the response is immediate and the access log records it.
  EOT
  type        = number
  default     = 50
}

variable "throttle_burst_limit" {
  description = "Requests allowed in a momentary spike above the steady rate."
  type        = number
  default     = 100
}

variable "ssm_prefix" {
  description = <<-EOT
    Parameter Store prefix the handler reads configuration from at cold start,
    e.g. "/sportable/staging".

    Only the prefix is passed. The values stay in Parameter Store so that
    changing a distance band is a parameter write, not a release.
  EOT
  type        = string
}

# ------------------------------------------------------------- Access Assistant
# Epic 6. Everything below is inert unless enable_assistant is true.

variable "enable_assistant" {
  description = <<-EOT
    Create the Access Assistant function, its route and its throttle.

    Off by default: prod and iteration-1 call this module and neither runs an
    assistant. Enabling it in an environment whose network module has
    enable_bedrock_endpoint = false will deploy a function that cannot reach
    Bedrock — the call will hang rather than fail, so set both together.
  EOT
  type        = bool
  default     = false
}

variable "assistant_route_path" {
  description = "Path for the assistant route. Used by both the route and its throttle, so they cannot drift apart."
  type        = string
  default     = "/api/v1/assistant"
}

variable "assistant_memory_mb" {
  description = "Memory for the assistant function. A starting point to tune against measured latency, not a considered figure."
  type        = number
  default     = 1024
}

variable "assistant_timeout_seconds" {
  description = "Function timeout. Longer than the API's because a model call is slower than a database read."
  type        = number
  default     = 30
}

variable "assistant_integration_timeout_ms" {
  description = "API Gateway integration timeout. Below the function timeout, so the function decides the outcome rather than the gateway."
  type        = number
  default     = 29000
}

variable "assistant_throttle_rate_limit" {
  description = <<-EOT
    Steady-state requests per second for the assistant route ALONE.

    Deliberately far below the stage default. Every request here can invoke a
    model and the endpoint is public and unauthenticated, so this number is the
    cost ceiling. Raise it only with a spend alarm in place and an eye on the
    credit balance.
  EOT
  type        = number
  default     = 2
}

variable "assistant_throttle_burst_limit" {
  description = "Burst allowance for the assistant route. Enough for a person typing quickly, not enough for a loop."
  type        = number
  default     = 10
}

variable "bedrock_text_model_id" {
  # Haiku 4.5 has no on-demand throughput in ap-southeast-2: it is reachable only
  # through an inference profile, and the bare model id fails with "on-demand
  # throughput isn't supported". The au. profile keeps traffic in Australia
  # (Sydney and Melbourne); the IAM grant must cover the profile ARN and the
  # foundation-model ARN in both ap-southeast-2 and ap-southeast-4.
  description = "Model for intent and slot extraction. An inference profile id, not a bare model id."
  type        = string
  default     = "au.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "bedrock_embedding_model_id" {
  description = "Model for embeddings, at ingest and per query. Confirmed available in ap-southeast-2."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "assistant_config" {
  description = <<-EOT
    Assistant tunables, passed as one JSON blob the way SEARCH_CONFIG already
    is: retrieval depth, the relevance floor, token ceilings and the daily
    invocation cap. Resolved at apply time so a threshold changes with a
    pipeline run rather than a code change.
  EOT
  type        = map(string)
  default = {
    retrieval_top_k      = "4"
    relevance_floor      = "0.35"
    max_input_tokens     = "2000"
    max_output_tokens    = "500"
    daily_invocation_cap = "2000"
  }
}

variable "bedrock_bridge_ssm_prefix" {
  description = <<-EOT
    TEMPORARY. SSM path holding access_key_id and secret_access_key for an
    account that IS allowlisted for Bedrock, while this one is not. When set,
    the Bedrock-calling functions get BEDROCK_ACCESS_KEY_ID and
    BEDROCK_SECRET_ACCESS_KEY and sign their Bedrock calls with them. Empty
    (the default) means they use the execution role, the permanent
    arrangement. Clear this, apply, then delete the key in the other account.
  EOT
  type        = string
  default     = ""
}

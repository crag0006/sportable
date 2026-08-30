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
    ROOT of the zip — so `stub.handler` means stub.py, not handlers/stub.py.
  EOT
  type        = string
  default     = "stub.handler"
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

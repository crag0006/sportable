variable "name_prefix" {
  description = "Prefix for resource names and Name tags, e.g. \"sportable-staging\"."
  type        = string
}

variable "account_id" {
  description = <<-EOT
    AWS account id. Two uses, both load-bearing.

    Bucket names must be unique across every AWS account on earth, so
    "sportable-staging-raw" alone would collide. And the S3 invoke permission
    is scoped with source_account, without which any bucket in any account
    could invoke the load function by claiming to be S3.
  EOT
  type        = string
}

variable "environment" {
  description = "Environment name, passed to both handlers for log context."
  type        = string
  default     = "staging"
}

variable "source_dir" {
  description = <<-EOT
    Directory zipped as the deployment package — the repository's data/ folder.

    It becomes the zip ROOT, which is why the handler paths are
    `ingestion.fetch.handler` rather than `data.ingestion.fetch.handler`.
    data/README.md records the same convention.
  EOT
  type        = string
}

variable "execution_role_arn" {
  description = <<-EOT
    Pre-built Lambda execution role, hardcoded as an ARN rather than resolved
    with a data source: this account's principals cannot create IAM roles, and
    iam:ListAttachedRolePolicies is denied, so we can neither build nor inspect
    it.

    Both ingestion functions use it. It needs, at minimum:
      s3:PutObject, s3:GetObject on the raw and quarantine buckets
      AWSLambdaVPCAccessExecutionRole, for the load function's ENI

    If either function fails at runtime with AccessDenied, the error names the
    exact action and only the account holder can add it.
  EOT
  type        = string
}

variable "runtime" {
  description = "Matches the API function, so there is one Python version to reason about."
  type        = string
  default     = "python3.12"
}

variable "sources" {
  description = <<-EOT
    The source registry: one entry per open-data publisher.

    Keys must match the extractor module names in data/ingestion/extractors/
    AND the S3 key prefix, because the load function derives the dataset name
    by splitting the key on its first slash.

    `url` may be empty. That is the expected state until the Data team supplies
    real endpoints — the schedule is created but left DISABLED, so the shell is
    visible in the console without being able to fire against a source nobody
    has configured.

    Cadences are staggered on purpose: this account's total Lambda concurrency
    is 10, and four simultaneous multi-megabyte fetches is a self-inflicted
    throttle.
  EOT
  type = map(object({
    schedule_expression = string
    url                 = string
  }))

  validation {
    condition     = alltrue([for k, _ in var.sources : can(regex("^[a-z][a-z0-9_]*$", k))])
    error_message = "Source keys must be lowercase snake_case — they become S3 key prefixes and Python module names."
  }

  validation {
    condition = alltrue([
      for _, v in var.sources : can(regex("^(rate|cron)\\(", v.schedule_expression))
    ])
    error_message = "Each schedule_expression must be a rate(...) or cron(...) expression."
  }
}

variable "subnet_ids" {
  description = "Private subnets for the LOAD function only. The fetch function has no vpc_config."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group for the load function's ENI — the same one the API uses."
  type        = string
}

variable "database_url" {
  description = <<-EOT
    Connection string for the load function, read from Parameter Store at apply
    time by the runner.

    Passed in rather than read at runtime for the same reason the API's search
    config is: a function inside this VPC has no route to Parameter Store, and
    an SDK call there hangs until the function times out.
  EOT
  type        = string
  sensitive   = true
}

variable "alerts_topic_arn" {
  description = <<-EOT
    T5's SNS topic. Ingestion alarms publish here rather than creating a second
    topic — one place to confirm a subscription, one place to look when mail
    arrives.
  EOT
  type        = string
}

variable "fetch_memory_mb" {
  description = "The fetch function reads a response into memory and writes it out. Small is fine."
  type        = number
  default     = 256
}

variable "fetch_timeout_seconds" {
  description = <<-EOT
    Must EXCEED the handler's own 20 s HTTP timeout, or a slow publisher
    produces an opaque Lambda timeout instead of a readable error naming the
    dataset and the URL.
  EOT
  type        = number
  default     = 60

  validation {
    condition     = var.fetch_timeout_seconds > 20
    error_message = "Must exceed the handler's 20s HTTP timeout, or errors become unreadable."
  }
}

variable "load_memory_mb" {
  description = <<-EOT
    Larger than fetch, and not really about memory: Lambda scales CPU with
    memory, and this function parses files. It will also hold a GTFS archive
    once the real loaders land.
  EOT
  type        = number
  default     = 512
}

variable "load_timeout_seconds" {
  description = "Generous — a first load over a cold RDS instance is slow."
  type        = number
  default     = 120
}

variable "log_retention_days" {
  description = <<-EOT
    Explicit, because the default is NEVER EXPIRE. Left implicit, Lambda creates
    the group itself and the logs quietly consume the 5 GB free tier, then bill
    forever. Matches the other three groups in this account.
  EOT
  type        = number
  default     = 14
}

variable "archive_after_days" {
  description = <<-EOT
    Days before a raw object moves to Glacier Instant Retrieval.

    Instant Retrieval, not Deep Archive: a re-run over archived data must not
    need a restore job and a wait.
  EOT
  type        = number
  default     = 90
}

variable "noncurrent_version_expiry_days" {
  description = <<-EOT
    Days before a superseded VERSION is deleted. Current objects never expire.

    Versioning without this is how a bucket quietly accumulates every weekly
    fetch, forever.
  EOT
  type        = number
  default     = 180
}

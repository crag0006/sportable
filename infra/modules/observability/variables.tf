variable "name_prefix" {
  description = "Prefix for resource names and Name tags, e.g. \"sportable-staging\"."
  type        = string
}

variable "alert_emails" {
  description = <<-EOT
    Addresses subscribed to the alerts topic.

    EVERY ADDRESS MUST CLICK A CONFIRMATION LINK before it receives anything.
    Terraform creates the subscription and AWS sends the request; the click
    happens outside Terraform and cannot be automated. A subscription stuck in
    `PendingConfirmation` looks identical to a working one in `terraform show`.

    Start with the person who is on the hook for the system. Adding teammates
    who did not ask for alarm mail is how a team learns to filter it away.
  EOT
  type        = list(string)

  validation {
    condition     = length(var.alert_emails) > 0
    error_message = "At least one address, or the alarms have nowhere to go."
  }

  validation {
    condition     = alltrue([for e in var.alert_emails : can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", e))])
    error_message = "Each entry must look like an email address."
  }
}

variable "function_name" {
  description = "API Lambda function name, for the Lambda alarms' dimension."
  type        = string
}

variable "function_timeout_seconds" {
  description = <<-EOT
    The API function's configured timeout. The duration alarm fires at 80% of
    it, so this must track modules/api rather than being guessed here.
  EOT
  type        = number
}

variable "api_id" {
  description = "HTTP API id, for the API Gateway alarm's dimension."
  type        = string
}

variable "db_instance_identifier" {
  description = "RDS instance identifier, for the database alarms' dimension."
  type        = string
}

variable "db_connection_threshold" {
  description = <<-EOT
    Connection count that triggers the alarm.

    db.t4g.micro allows roughly 112 (LEAST(DBInstanceClassMemory/9531392, 5000)).
    40 leaves a wide margin while still firing early enough to investigate.
  EOT
  type        = number
  default     = 40
}

variable "db_free_storage_threshold_gb" {
  description = <<-EOT
    Free storage below which the alarm fires, in gigabytes.

    The instance has 20 GB and storage autoscaling is deliberately off, so this
    condition does not resolve itself.
  EOT
  type        = number
  default     = 2
}

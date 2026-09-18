# ==============================================================================
# ingestion module — inputs
# ==============================================================================
# Stage 1 (fetch) runs outside the VPC because it must reach the publishers over
# the internet. Stages 2 and 3 (transform/load, derive) run inside the VPC
# because they must reach RDS. That split is the reason this module takes both
# a subnet list and, separately, nothing at all for fetch.
#
# NOTE what this module does NOT create: IAM roles. This account's principals
# hold PowerUserAccess, which excludes IAM entirely, so every role is built by
# the account holder and passed in here as an ARN — the same contract the api
# module already uses.
# ==============================================================================

variable "name_prefix" {
  description = "Prefix for every resource name, e.g. sportable-staging."
  type        = string
}

variable "account_id" {
  description = <<-EOT
    Account id, used to make the bucket names globally unique. S3 bucket names
    are a global namespace, so "sportable-staging-raw" is very likely already
    taken by someone else on the planet.
  EOT
  type        = string
}

variable "execution_role_arn" {
  description = <<-EOT
    Pre-built Lambda execution role, shared by all three functions.

    Must carry AWSLambdaVPCAccessExecutionRole (ENI management for the in-VPC
    functions, plus CloudWatch Logs), S3 read/write on the raw and quarantine
    buckets including s3:PutObjectTagging, and ssm:GetParameter with kms:Decrypt
    for the database URL.

    Its trust policy must allow lambda.amazonaws.com.
  EOT
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/", var.execution_role_arn))
    error_message = "execution_role_arn must be a full IAM role ARN."
  }
}

variable "subnet_ids" {
  description = <<-EOT
    Private subnets for the in-VPC functions. Pass the first private subnet only
    (az-a): the RDS instance lives there and a second ENI in az-b would buy
    nothing but a longer cold start.
  EOT
  type        = list(string)
}

variable "security_group_id" {
  description = "Lambda security group, the same one the api module uses."
  type        = string
}

variable "ssm_db_url_parameter" {
  description = <<-EOT
    SSM parameter name holding the database connection string. The name, not the
    value: the value is a SecureString and must never pass through Terraform
    state or a plan output.
  EOT
  type        = string
}

variable "fetch_source_dir" {
  description = <<-EOT
    Built package directory for the fetch function. Contains handler.py, its
    dependencies installed for Lambda's platform, and a sources/ directory of
    YAML source cards — handler.py resolves REGISTER_DIR to /var/task/sources.

    This is the BUILT package, not the source tree. Something must run the
    packaging step before terraform, in CI and by hand alike.
  EOT
  type        = string
}

variable "load_source_dir" {
  description = "Built package directory for the transform/load function."
  type        = string
}

variable "derive_source_dir" {
  description = "Built package directory for the status builder function."
  type        = string
}

variable "schedules" {
  description = <<-EOT
    One EventBridge rule per entry. The key becomes the rule name suffix; the
    value carries the cron expression and the source ids passed to the fetch
    function as a constant JSON payload.

    Cadence follows the publisher, not our convenience. A source polled more
    often than it is published costs quota and returns 304s; polled less often,
    the staleness banner fires on data that was fine.

    ONLY DS-09 IS SCHEDULED. Iteration 2 scope decision, 15 Sep 2026: event data
    is the only thing that churns. Programmes start and end weekly, so AAA Play
    is polled weekly. Facilities, public toilets, transit and the ABS boundary
    layers are reference data on a scale of months to years — they are loaded
    ONCE by hand through data/scripts/load_run.py over the bastion tunnel, and a
    weekly rule fetching them would spend requests to re-confirm what has not
    moved.

    The consequence is deliberate and visible: a one-time load freezes
    publisher_last_updated, so those sources cross their staleness thresholds on
    the calendar and their facts start carrying "possibly out of date" in the
    interface. That warning is TRUE — we are not refetching, so the fact may
    indeed be out of date — and it must not be silenced by raising the threshold.
    The threshold describes our refresh policy, not the publisher's cadence, and
    the honest reading of a one-time load is exactly what the banner says.

    Re-enabling a source is adding its entry back here, not a code change. The
    fetch function and the load function already handle DS-01 and DS-02.
  EOT

  type = map(object({
    schedule_expression = string
    source_ids          = list(string)
    description         = string
  }))

  default = {
    # DS-09 GETS ITS OWN SLOT, AND THAT IS THE WHOLE POINT OF THE ENTRY.
    #
    # handler.py raises at the end of a run if ANY source in the payload
    # failed, so every source sharing a rule shares a fate. The other eight
    # sources are file downloads from government portals with pinned hashes.
    # DS-09 is a live third-party WordPress API on somebody else's server,
    # behind Wordfence, with no contract with us and no obligation to keep its
    # shape. It is by far the most likely source in the register to fail on any
    # given week, and grouping it with DS-04/06/07/08 would let one AAA Play
    # timeout mark the ABS boundaries as failed too.
    #
    # 16:30 UTC Sunday: weekly, matching the card's cadence, and staggered
    # thirty minutes clear of the transit pull at 16:00 (the largest payload,
    # which runs alone) and thirty minutes clear of the monthly boundaries run
    # at 17:00. Nothing else in this map touches that slot.
    #
    # NO TIMEOUT CHANGE IS NEEDED and none is made. The pull measured on
    # 11 Sep 2026 took 28.06 seconds over 18 HTTP requests — six activity
    # pages, six facility pages, two organisation pages and four taxonomies —
    # and landed 15.4 MB as ONE S3 object, aaaplay/dt=YYYY-MM-DD/aaaplay.json.
    # Against fetch_timeout_seconds of 900 that is roughly 3% of the budget, so
    # the publisher could get thirty times slower before this rule is the thing
    # that breaks. The single object is deliberate: see the source card and
    # extractors/aaaplay.py for why eighteen responses become one body.
    aaaplay = {
      schedule_expression = "cron(30 16 ? * SUN *)"
      source_ids          = ["DS-09"]
      description         = "AAA Play activity finder (Access for All Abilities), published weekly. Live API, so it runs alone."
    }
  }
}

variable "fetch_timeout_seconds" {
  description = <<-EOT
    handler.py allows a 120s HTTP timeout and up to MAX_ATTEMPTS tries with
    exponential backoff, and one rule can cover four sources. 900 is Lambda's
    ceiling and the only value that survives a slow publisher on a bad day.
  EOT
  type        = number
  default     = 900
}

variable "fetch_memory_mb" {
  description = <<-EOT
    handler.py reads the whole response body into memory before hashing it. The
    GTFS archive is the sizing constraint here, not the CPU.
  EOT
  type        = number
  default     = 1024
}

variable "load_memory_mb" {
  description = <<-EOT
    The transform holds a dataframe and the loader runs spatial joins. Memory
    also buys proportional CPU on Lambda, which is what actually shortens the
    nearest-amenity search.
  EOT
  type        = number
  default     = 2048
}

variable "log_retention_days" {
  description = <<-EOT
    CloudWatch log retention. Lambda defaults to never expire, which bills
    forever. 14 days matches the retention already set across this stack — see
    the infrastructure design document, section 1.1.
  EOT
  type        = number
  default     = 14
}

variable "alarm_topic_arn" {
  description = <<-EOT
    SNS topic for alarms. Empty string means create the alarms but leave them
    unwired — useful before the observability module is extended to cover the
    pipeline functions.
  EOT
  type        = string
  default     = ""
}

variable "tags" {
  description = "Merged into every taggable resource."
  type        = map(string)
  default     = {}
}

variable "enable_extended_alarms" {
  description = <<-EOT
    Duration-near-timeout and hash-pin alarms, off by default.

    CloudWatch's Free Tier allows TEN alarms in total and this stack already
    uses six. Three Errors alarms take that to nine. Turning this on adds four
    more and takes the account to thirteen — past the allowance, on an account
    with no budget alarm to notice. Enable deliberately, not by default.
  EOT
  type        = bool
  default     = false
}

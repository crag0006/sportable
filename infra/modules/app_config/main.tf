# ==============================================================================
# Application configuration — SSM Parameter Store
# ==============================================================================
#
# WHAT THIS SOLVES
#   AC1.2.4 lets a user choose 250 m, 500 m or 1 km. Those three numbers have to
#   live somewhere. The tempting place is a constant in the handler:
#
#       DISTANCE_BANDS = [250, 500, 1000]     # <- do not do this
#
#   Then "make 750 m an option" becomes a code change, a pull request, a CI run
#   and a deploy. Here it is one `aws ssm put-parameter` and a Lambda cold
#   start — no release, no reviewer, no downtime.
#
#   That matters most in the demo. If a marker asks "what if the corridor were
#   wider?", the answer should be a shrug and thirty seconds, not "that is a
#   code change."
#
# WHY PARAMETER STORE AND NOT SECRETS MANAGER
#   None of this is secret. Secrets Manager charges USD $0.40 per secret per
#   month and exists for values that need rotation. Standard SSM parameters are
#   free, versioned, and auditable through CloudTrail. The database password
#   already sits in SSM as a SecureString — see modules/database.
#
# THE READ PATH, AND ITS ONE PERMISSION
#   The API reads these at cold start with GetParametersByPath, so the whole
#   tree arrives in one call and is then cached for the life of the execution
#   environment. That costs one API call per cold start, not one per request.
#
#   The Lambda execution role must therefore allow `ssm:GetParametersByPath` on
#   this prefix. That role was pre-built by the account holder and we can
#   neither read nor change it, so whether it works is a question the running
#   system answers — see the /api/v1/config endpoint and the runbook.
# ==============================================================================

# ------------------------------------------------------------------------------
# Search behaviour
# ------------------------------------------------------------------------------

# StringList rather than four separate parameters: the bands are one decision,
# and they are read together. Splitting them would let the tree drift into a
# state where the default is not one of the offered bands.
resource "aws_ssm_parameter" "distance_bands" {
  # checkov:skip=CKV2_AWS_34:Deliberately plaintext. These are public product
  # settings — the radii shown in the UI, and how old data may be before it is
  # labelled stale. A SecureString would add a KMS decrypt to every cold start
  # and hide values that are meant to be readable at a glance during a demo.
  # The contrast is intentional: modules/database stores the password as a
  # SecureString, in the same tree, because that one IS a secret.
  name  = "${var.ssm_prefix}/search/distance_bands_m"
  type  = "StringList"
  value = join(",", var.distance_bands_m)

  description = "Corridor and proximity radii offered in the UI, in metres. AC1.2.4."


  # Terraform sets this once, then stops managing the value. Without this, an
  # operator changing the band with `aws ssm put-parameter` would have it
  # silently reverted by the next pipeline apply — and the whole point of T5 is
  # that tuning these does not require editing a file and opening a PR.
  #
  # The trade: the precondition below validates the VARIABLES, not whatever an
  # operator later writes. Setting a default outside the offered bands by hand
  # is possible, and would show a result set no click reproduces. If that
  # becomes a real risk, validate it in the handler instead.
  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.name_prefix}-distance-bands" }
}

resource "aws_ssm_parameter" "default_band" {
  # checkov:skip=CKV2_AWS_34:Deliberately plaintext. These are public product
  # settings — the radii shown in the UI, and how old data may be before it is
  # labelled stale. A SecureString would add a KMS decrypt to every cold start
  # and hide values that are meant to be readable at a glance during a demo.
  # The contrast is intentional: modules/database stores the password as a
  # SecureString, in the same tree, because that one IS a secret.
  name  = "${var.ssm_prefix}/search/default_distance_m"
  type  = "String"
  value = tostring(var.default_distance_m)

  description = "Radius applied before the user chooses one. Must be one of distance_bands_m."

  # A default that is not one of the offered bands would show the user a result
  # set they cannot reproduce by clicking anything. Caught at plan time, which
  # is the cheapest place to catch it.
  lifecycle {
    # Set once, then left to operators — see the note on distance_bands.
    ignore_changes = [value]

    precondition {
      condition     = contains(var.distance_bands_m, var.default_distance_m)
      error_message = "default_distance_m (${var.default_distance_m}) must be one of distance_bands_m (${join(", ", [for b in var.distance_bands_m : tostring(b)])})."
    }
  }

  tags = { Name = "${var.name_prefix}-default-band" }
}

resource "aws_ssm_parameter" "max_results" {
  # checkov:skip=CKV2_AWS_34:Deliberately plaintext. These are public product
  # settings — the radii shown in the UI, and how old data may be before it is
  # labelled stale. A SecureString would add a KMS decrypt to every cold start
  # and hide values that are meant to be readable at a glance during a demo.
  # The contrast is intentional: modules/database stores the password as a
  # SecureString, in the same tree, because that one IS a secret.
  name        = "${var.ssm_prefix}/search/max_results"
  type        = "String"
  value       = tostring(var.max_results)
  description = "Upper bound on venues returned by one search, to cap query cost."


  # Terraform sets this once, then stops managing the value. Without this, an
  # operator changing the band with `aws ssm put-parameter` would have it
  # silently reverted by the next pipeline apply — and the whole point of T5 is
  # that tuning these does not require editing a file and opening a PR.
  #
  # The trade: the precondition below validates the VARIABLES, not whatever an
  # operator later writes. Setting a default outside the offered bands by hand
  # is possible, and would show a result set no click reproduces. If that
  # becomes a real risk, validate it in the handler instead.
  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.name_prefix}-max-results" }
}

# ------------------------------------------------------------------------------
# Data freshness
# ------------------------------------------------------------------------------
#
# AC1.3.2 requires every access fact to show its source and how current that
# source is. "How current" needs a threshold, and the right threshold differs by
# publisher: a weekly feed silent for ten days is late, while OSM silent for ten
# days is entirely normal.
#
# Each threshold is deliberately LONGER than its publisher's cadence. Set them
# equal and one missed refresh — a public holiday, a portal outage — marks the
# data stale and the UI starts apologising for nothing.
resource "aws_ssm_parameter" "staleness" {
  # checkov:skip=CKV2_AWS_34:Deliberately plaintext. These are public product
  # settings — the radii shown in the UI, and how old data may be before it is
  # labelled stale. A SecureString would add a KMS decrypt to every cold start
  # and hide values that are meant to be readable at a glance during a demo.
  # The contrast is intentional: modules/database stores the password as a
  # SecureString, in the same tree, because that one IS a secret.
  for_each = var.source_staleness_days

  name        = "${var.ssm_prefix}/data/staleness_days/${each.key}"
  type        = "String"
  value       = tostring(each.value)
  description = "Days after which ${each.key} data is presented as stale. AC1.3.2."

  tags = { Name = "${var.name_prefix}-staleness-${each.key}" }
}

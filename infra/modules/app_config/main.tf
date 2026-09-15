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

# ------------------------------------------------------------------------------
# Events — DS-09, AAA Play
# ------------------------------------------------------------------------------
#
# WHY THESE THREE ARE PARAMETERS AND NOT CONSTANTS
#   Every other source in the register is a file download from a government
#   portal, pinned by SHA-256, with a published licence and a publisher who
#   announces changes. DS-09 is none of those things. It is a live WordPress
#   REST API run by a not-for-profit on their own marketing site, unversioned —
#   /wp-json/wp/v2 carries no contract, no deprecation policy and no agreement
#   with this project. Nobody at Reclink owes us notice before a hostname
#   changes, a plugin rewrites a route, or a CDN is put in front of it.
#
#   The failure that follows is not subtle. The weekly fetch starts returning
#   404s, the pipeline logs FETCH_FAILED, and the events page quietly serves
#   whatever was last loaded — stale programmes a user can travel to and find
#   cancelled. The fix is one string.
#
#   If that string lives in extractors/aaaplay.py it is a code change: edit,
#   review, rebuild the Lambda package, apply. Here it is
#   `aws ssm put-parameter --overwrite` and the next cold start. On a weekly
#   pipeline that is the difference between fixing it before Sunday and
#   missing a refresh.
#
#   The module's own BASE_URL stays as the compiled-in fallback so the
#   extractor still runs locally with no AWS at all. Note the two are not
#   byte-identical: the module carries the apex host and this parameter carries
#   the www host given by the events task. Both resolve and urllib follows the
#   redirect either way, but the PARAMETER is the authoritative value — the
#   constant is only what a laptop falls back to.

resource "aws_ssm_parameter" "events_scope" {
  # checkov:skip=CKV2_AWS_34:Deliberately plaintext. "victoria" is a public
  # product setting — it is printed on the page it governs. A SecureString
  # would add a KMS decrypt to every cold start to hide a word the interface
  # displays. modules/database stores the database password as a SecureString
  # in this same tree, because that one IS a secret.
  name  = "${var.ssm_prefix}/events/scope"
  type  = "String"
  value = var.events_scope

  description = "Geographic scope of the events epic. DS-09 is a statewide publisher."

  # Set once, then left to operators — see the note on distance_bands.
  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.name_prefix}-events-scope" }
}

resource "aws_ssm_parameter" "aaa_play_base_url" {
  # checkov:skip=CKV2_AWS_34:Deliberately plaintext. This is the public root of
  # a public WordPress API that anyone can curl without a key — the source card
  # records /wp-json/ reporting "authentication": []. There is no credential to
  # protect, and encrypting it would only add a KMS decrypt to the fetch
  # Lambda's cold start.
  name  = "${var.ssm_prefix}/events/aaa_play_base_url"
  type  = "String"
  value = var.aaa_play_base_url

  description = "Root of the AAA Play WordPress REST API. Changeable without a release — see main.tf."

  # Set once, then left to operators. This is the parameter the whole rationale
  # above is about: an operator changing it at 22:00 on a Saturday must not
  # have it reverted by the next pipeline apply.
  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.name_prefix}-aaa-play-base-url" }
}

resource "aws_ssm_parameter" "aaa_play_page_size" {
  # checkov:skip=CKV2_AWS_34:Deliberately plaintext. A pagination size is not a
  # secret; it is a politeness setting for a public API.
  name  = "${var.ssm_prefix}/events/aaa_play_page_size"
  type  = "String"
  value = tostring(var.aaa_play_page_size)

  description = "WordPress per_page for the DS-09 pull. 100 is the API maximum."

  # Set once, then left to operators — the value to reach for first if the
  # publisher starts rate limiting us mid-pull.
  lifecycle {
    ignore_changes = [value]
  }

  tags = { Name = "${var.name_prefix}-aaa-play-page-size" }
}

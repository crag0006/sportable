# ==============================================================================
# iteration-1 — the submitted Iteration 1 build, on its own URL
# ==============================================================================
#
# WHY THIS ENVIRONMENT EXISTS
#   Staging has one bucket and one distribution, and every push to `dev`
#   overwrites them. Pointing the iteration URL at that distribution would mean
#   the Iteration 1 address showing Iteration 2 work the moment it starts.
#
#   So each iteration gets its own bucket and distribution, deployed from its
#   own release branch. The URL then keeps showing what was submitted.
#
# WHAT IS SHARED
#   The API, and through it the database. See api_origin_domain in variables.tf
#   for the reasoning and the risk that comes with it.
#
# This calls the same module staging does. That is the whole point of the
# modules/envs split — see docs/adr/ADR-001.
# ==============================================================================

module "static_site" {
  source = "../../modules/static_site"

  name_prefix = var.name_prefix
  account_id  = var.expected_account_id

  # Same origin for the SPA and the API, so the browser never makes a
  # cross-origin request and CORS never applies.
  api_origin_domain = var.api_origin_domain

  # Both names, so the apex and www serve the same site rather than one
  # redirecting to the other.
  aliases = var.enable_custom_domain ? [var.domain_name, "www.${var.domain_name}"] : []

  acm_certificate_arn = var.enable_custom_domain ? aws_acm_certificate.site.arn : null
}

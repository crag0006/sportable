# ==============================================================================
# prod — the product's permanent public address
# ==============================================================================
#
# WHAT THIS IS
#   sportablemelbourne.me, deployed from `main`. This is the address the product
#   is advertised at and the one that must keep working.
#
# HOW IT DIFFERS FROM THE OTHER ENVIRONMENTS
#   staging      dev branch,                 changes constantly, team use
#   iteration-N  release-iteration-N branch, frozen after submission, private
#   prod         main branch,                the public product
#
#   `main` moves only when a release is promoted, so this environment changes
#   far less often than staging. That is the point: it is the address people
#   are given, and it should not move under them.
#
# NO BASIC AUTH
#   The iteration sites are password protected while they are marked. This one
#   is not — it is public by definition. Anything that must not be public does
#   not belong here.
#
# WHAT IS SHARED
#   The API, and through it the database. See api_origin_domain in variables.tf
#   for the reasoning and the risk that comes with it.
#
# This calls the same module every other environment does — see docs/adr/ADR-001.
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

  # Deliberately absent: basic_auth_credentials. Production is public, and
  # leaving this unset renders the CloudFront function without an auth block
  # at all rather than with an empty password.
}

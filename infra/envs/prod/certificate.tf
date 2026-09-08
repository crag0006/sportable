# ==============================================================================
# TLS certificate for the iteration URL
# ==============================================================================
#
# Requested here, validated by hand at the registrar. That split is deliberate:
# the DNS for this domain lives at Namecheap, not in Route 53, so Terraform can
# create the certificate request but cannot prove we own the name.
#
# HOW THIS GOES
#   1. apply  — the certificate is created in PENDING_VALIDATION, immediately
#   2. read   — `terraform output dns_validation_records` prints what to add
#   3. add    — two CNAME records at Namecheap
#   4. wait   — ACM notices within a few minutes and the status becomes ISSUED
#   5. apply  — with enable_custom_domain = true, CloudFront picks it up
#
# There is no `aws_acm_certificate_validation` resource on purpose. It blocks
# the apply until the records exist, which would mean a pipeline run hanging on
# a human editing DNS in another browser tab.
# ==============================================================================

resource "aws_acm_certificate" "site" {
  # us-east-1, not Sydney. See the provider block for why.
  provider = aws.us_east_1

  domain_name               = var.domain_name
  subject_alternative_names = ["www.${var.domain_name}"]
  validation_method         = "DNS"

  # The replacement is created and validated before the old one is removed, so
  # renewing or adding a name never leaves the distribution without a
  # certificate.
  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = "${var.name_prefix}-cert" }
}

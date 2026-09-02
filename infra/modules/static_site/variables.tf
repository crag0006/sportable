variable "name_prefix" {
  description = "Prefix for resource names, e.g. \"sportable-staging\"."
  type        = string
}

variable "account_id" {
  description = <<-EOT
    Used only to make the bucket name globally unique. S3 bucket names are
    unique across every AWS account on earth, so "sportable-staging-site" is
    very likely taken by a stranger.
  EOT
  type        = string
}

variable "price_class" {
  description = <<-EOT
    Which CloudFront edge locations serve the site.

    PriceClass_All is chosen deliberately: the cheaper classes EXCLUDE Oceania,
    which would route Melbourne users via Singapore or the United States. For an
    application about Melbourne sports venues, serving Melbourne slowly to save
    a few cents is the wrong trade.
  EOT
  type        = string
  default     = "PriceClass_All"
}

variable "api_origin_domain" {
  description = <<-EOT
    Hostname of the API Gateway endpoint, without the scheme, e.g.
    "w9kjh1cuye.execute-api.ap-southeast-2.amazonaws.com".

    When set, the distribution gains an /api/* behaviour pointing at it. When
    null, the distribution serves only the SPA — which is how Step 1 shipped a
    working site before the API existed.

    ROUTING THE API THROUGH CLOUDFRONT IS THE POINT. The SPA and the API then
    share one origin, so the browser never makes a cross-origin request and CORS
    does not apply at all: no preflight, no Access-Control-Allow-Origin headers,
    and none of the class of bug where a request works in Postman and fails in
    the browser.
  EOT
  type        = string
  default     = null
}

variable "api_path_pattern" {
  description = "Which paths go to the API rather than to S3."
  type        = string
  default     = "/api/*"
}

variable "aliases" {
  description = <<-EOT
    Custom domain names this distribution answers on, e.g.
    ["sportablemelbourne-iteration1.me", "www.sportablemelbourne-iteration1.me"].

    Empty means the distribution is reachable only at its own
    *.cloudfront.net name, which is the right answer for staging.

    Setting this REQUIRES acm_certificate_arn: CloudFront will not accept an
    alias it has no certificate for, and the apply fails rather than serving
    the domain over a mismatched certificate.
  EOT
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = <<-EOT
    ACM certificate covering every name in `aliases`.

    MUST be issued in us-east-1. Not a preference — CloudFront reads
    certificates only from that region, whatever region the distribution
    serves. A certificate in ap-southeast-2 is invisible to it, and the error
    when you try says nothing about regions.

    null keeps the free default *.cloudfront.net certificate.
  EOT
  type        = string
  default     = null
}

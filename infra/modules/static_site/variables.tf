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

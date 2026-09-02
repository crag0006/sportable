variable "region" {
  description = "Sydney, matching staging. The certificate is the one exception — see providers.tf."
  type        = string
  default     = "ap-southeast-2"
}

variable "expected_account_id" {
  description = "The team account. Any other id aborts the plan — see providers.tf."
  type        = string
  default     = "725699850301"
}

variable "name_prefix" {
  description = <<-EOT
    Prefix for every resource name and Name tag.

    Distinct from staging's so the two environments cannot collide — S3 bucket
    names in particular are unique across every AWS account on earth.
  EOT
  type        = string
  default     = "sportable-iteration-1"
}

variable "domain_name" {
  description = "Apex domain for this iteration. www is added as a subject alternative name."
  type        = string
  default     = "sportablemelbourne-iteration1.me"
}

variable "enable_custom_domain" {
  description = <<-EOT
    Attach the aliases and the certificate to CloudFront.

    Leave FALSE until the certificate reads ISSUED. CloudFront rejects an alias
    whose certificate is still pending, and the apply fails partway.

        aws acm describe-certificate --region us-east-1 \
          --certificate-arn "$(terraform output -raw certificate_arn)" \
          --query 'Certificate.Status' --output text

    Flip it to true once that prints ISSUED, then apply again.
  EOT
  type        = bool
  default     = false
}

variable "api_origin_domain" {
  description = <<-EOT
    API Gateway host that /api/* is forwarded to.

    SHARED WITH STAGING, deliberately. Each iteration gets its own bucket and
    distribution so its frontend stays frozen, but a second Lambda and API
    Gateway would need this environment to reach into staging's VPC, subnets
    and security groups — real work for an isolation the frontend does not need.

    The trade is worth naming: if the API contract changes after this iteration
    is submitted, this URL breaks even though its own code never moved. If that
    happens, give this environment its own API rather than freezing dev.
  EOT
  type        = string
  default     = "w9kjh1cuye.execute-api.ap-southeast-2.amazonaws.com"
}

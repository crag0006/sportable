output "certificate_arn" {
  value = aws_acm_certificate.site.arn
}

output "dns_validation_records" {
  description = <<-EOT
    Add these at Namecheap as CNAME records, then wait for ACM to notice.

    Namecheap appends the domain to the Host field automatically, so strip the
    trailing ".sportablemelbourne-iteration1." from the name before pasting it —
    entering the full name produces a record for name.domain.domain, which never
    validates and gives no clue why.
  EOT
  value = [
    for o in aws_acm_certificate.site.domain_validation_options : {
      host  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  ]
}

output "cloudfront_domain" {
  description = "Point the apex ALIAS record and the www CNAME at this."
  value       = module.static_site.domain_name
}

output "distribution_id" {
  description = "For cache invalidation after each release deploy."
  value       = module.static_site.distribution_id
}

output "site_bucket" {
  description = "Deploy target: aws s3 sync frontend/dist s3://<this>/"
  value       = module.static_site.bucket_name
}

output "site_url" {
  description = "What the URL becomes once DNS points here."
  value       = var.enable_custom_domain ? "https://${var.domain_name}" : module.static_site.site_url
}

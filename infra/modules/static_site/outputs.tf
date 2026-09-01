output "bucket_name" {
  description = "Target for `aws s3 sync frontend/dist s3://<this>/` in the deploy pipeline."
  value       = aws_s3_bucket.site.id
}

output "bucket_arn" {
  value = aws_s3_bucket.site.arn
}

output "distribution_id" {
  description = "Needed for `aws cloudfront create-invalidation` after each deploy."
  value       = aws_cloudfront_distribution.site.id
}

output "distribution_arn" {
  value = aws_cloudfront_distribution.site.arn
}

output "domain_name" {
  description = "The CloudFront hostname."
  value       = aws_cloudfront_distribution.site.domain_name
}

output "site_url" {
  description = "The public address of the application. This is the demo URL."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

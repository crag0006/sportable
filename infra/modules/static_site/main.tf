# ==============================================================================
# static_site — private S3 bucket served over HTTPS by CloudFront
# ==============================================================================
#
# THE SHAPE
#   browser → CloudFront (HTTPS) → S3 (private, Origin Access Control)
#
#   The bucket blocks all public access. Its policy grants read to ONE
#   CloudFront distribution, matched by ARN. Fetching the S3 URL directly
#   returns 403. CloudFront is the only route in, so TLS is not optional and
#   cannot be bypassed.
#
# WHY NOT AN S3 WEBSITE ENDPOINT
#   It requires a world-readable bucket and serves plain HTTP only. There is no
#   way to put a certificate on it.
#
# WHY OAC AND NOT OAI
#   Origin Access Identity is the previous mechanism, still widely copied from
#   older tutorials. Origin Access Control replaced it, supports SSE-KMS, and is
#   what AWS now documents.
#
# NO CUSTOM DOMAIN IN ITERATION 1
#   CloudFront issues every distribution a working HTTPS name for free
#   (d1234abcd.cloudfront.net), which satisfies "a public HTTPS address".
#   Adding a real domain later means an ACM certificate IN us-east-1 — a genuine
#   cross-region requirement — plus DNS validation and an alias record.
# ==============================================================================

# ---------------------------------------------------------------- the bucket
resource "aws_s3_bucket" "site" {
  # checkov:skip=CKV_AWS_18:Access logging would need a second bucket that
  #   itself needs logging. CloudFront access logs are the useful ones for a
  #   web front end, and those are addressed separately below.
  # checkov:skip=CKV_AWS_144:Cross-region replication protects irreplaceable
  #   data. This bucket holds a build artefact that CI regenerates from source
  #   on every deploy.
  # checkov:skip=CKV_AWS_145:AES256 rather than SSE-KMS. A customer managed key
  #   costs ~USD $1/month plus per-request charges to encrypt a public website
  #   bundle that is served unencrypted to every visitor by design.
  # checkov:skip=CKV2_AWS_62:Nothing consumes S3 event notifications here.
  # checkov:skip=CKV2_AWS_61:Lifecycle rules are configured below; the graph
  #   check does not always associate them across resources.
  bucket = "${var.name_prefix}-site-${var.account_id}"

  tags = { Name = "${var.name_prefix}-site" }
}

# Versioning is what lets you recover from a bad deploy by restoring the
# previous object version, without a rebuild.
resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# All four stay on. Origin Access Control works WITH the public access block —
# the bucket policy grants CloudFront's service principal, not the public.
resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning without expiry keeps every superseded bundle forever. Each deploy
# replaces the whole set of assets, so old versions accumulate quickly.
resource "aws_s3_bucket_lifecycle_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    id     = "expire-old-bundle-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ------------------------------------------------------- origin access control
# Signs CloudFront's requests to S3 with SigV4. The bucket policy below then
# trusts that signature — scoped to this one distribution.
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.name_prefix}-oac"
  description                       = "Signs CloudFront requests to the SPA bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ------------------------------------------------------------ SPA rewrite fn
resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "${var.name_prefix}-spa-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Rewrites extensionless paths to /index.html for the SPA router"
  publish = true
  code    = file("${path.module}/functions/spa-rewrite.js")
}

# --------------------------------------------------------------- distribution
resource "aws_cloudfront_distribution" "site" {
  # checkov:skip=CKV_AWS_174:The viewer certificate is CloudFront's default
  #   *.cloudfront.net certificate, for which AWS fixes the minimum TLS version
  #   and does not allow it to be raised. Setting TLSv1.2_2021 requires a custom
  #   domain and an ACM certificate in us-east-1, which Iteration 1 does not
  #   have. This is a real limitation of the no-domain decision, recorded rather
  #   than hidden. Revisit when a domain is registered.
  # checkov:skip=CKV_AWS_68:AWS WAF costs ~USD $5/month plus per-rule and
  #   per-request charges to protect a read-only site serving public open data
  #   with no authentication and no write path.
  # checkov:skip=CKV_AWS_86:CloudFront access logging needs a dedicated log
  #   bucket with its own ACL configuration and lifecycle. Deferred to T5, where
  #   observability is the task rather than a side effect.
  # checkov:skip=CKV_AWS_310:Origin failover needs a second origin. There is one
  #   bucket; a failover group would point at itself.
  # checkov:skip=CKV2_AWS_42:A custom SSL certificate requires a custom domain,
  #   which Iteration 1 does not have. Same root cause as CKV_AWS_174 above.
  # checkov:skip=CKV2_AWS_47:Follows from having no WAF. There is no WebACL to
  #   attach a Log4j managed rule group to, and no Java in this stack.
  # checkov:skip=CKV2_AWS_32:A response headers policy IS attached — the
  #   AWS-managed SecurityHeadersPolicy, by id, in default_cache_behavior below.
  #   This graph check only recognises a reference to an
  #   aws_cloudfront_response_headers_policy RESOURCE, so it cannot see a
  #   managed policy. Defining our own would satisfy the scanner but means
  #   hand-writing a Content-Security-Policy for a front end that does not exist
  #   yet — a good way to block the Frontend team's map tiles in week three.
  #   Verified after apply with:
  #     curl -sI https://<domain>/ | grep -i strict-transport-security
  # checkov:skip=CKV_AWS_374:Geo restriction is deliberately NOT enabled.
  #   Restricting to Australia would block markers, teammates travelling, and
  #   any user on a VPN — and this is a public accessibility service. Blocking
  #   people by location is the opposite of what the product is for.
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${var.name_prefix} SPA"
  price_class         = var.price_class
  default_root_object = "index.html"

  origin {
    origin_id                = "s3-spa"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  # The API origin, added only when an API exists. A custom origin (not S3), so
  # it needs explicit protocol settings.
  dynamic "origin" {
    for_each = var.api_origin_domain == null ? [] : [var.api_origin_domain]

    content {
      origin_id   = "apigw"
      domain_name = origin.value

      custom_origin_config {
        origin_protocol_policy = "https-only"
        http_port              = 80
        https_port             = 443
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # /api/* is evaluated BEFORE the default behaviour. Ordered behaviours are
  # matched most-specific-first regardless of declaration order, but keeping the
  # intent visible here matters more than relying on that.
  dynamic "ordered_cache_behavior" {
    for_each = var.api_origin_domain == null ? [] : [1]

    content {
      path_pattern           = var.api_path_pattern
      target_origin_id       = "apigw"
      viewer_protocol_policy = "redirect-to-https"

      # Every method: the API will accept POST and PATCH once it does more than
      # read. OPTIONS is included for completeness even though same-origin
      # requests never trigger a preflight.
      allowed_methods = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods  = ["GET", "HEAD"]
      compress        = true

      # Managed-CachingDisabled. Verified by name against the API.
      #
      # THIS IS THE ONE THAT WILL BITE IF IT IS WRONG. With the default policy,
      # CloudFront would serve a venue search result for 24 hours and the request
      # would never reach Lambda — invisible in the API's own logs, because there
      # is no request to log.
      cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"

      # Managed-AllViewerExceptHostHeader.
      #
      # Forwards query strings, cookies and headers to the origin, but NOT the
      # viewer's Host header. API Gateway rejects a request whose Host does not
      # match its own domain, producing a 403 that looks like an authorisation
      # failure and is not. Using plain AllViewer here is a classic mistake.
      origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

      # Security headers on API responses too.
      response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03"
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3-spa"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # AWS-managed CachingOptimized (verified by name against the API, not
    # copied from a blog post). Safe for a SPA bundle because the build gives
    # every asset a content-hashed filename — a changed file is a new URL.
    # index.html is the exception, and the deploy pipeline invalidates it.
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    # Attached to THIS behaviour only, which is the whole point: /api/* has no
    # function association and its responses pass through untouched.
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }

    # AWS-managed SecurityHeadersPolicy. Adds Strict-Transport-Security,
    # X-Content-Type-Options, X-Frame-Options, Referrer-Policy and a
    # Content-Security-Policy to every response. Free, and it closes a whole
    # class of browser-side issues that are tedious to retrofit.
    response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03"
  }

  # NO custom_error_response BLOCKS, DELIBERATELY.
  #
  # They are DISTRIBUTION-WIDE in CloudFront — there is no per-behaviour
  # override. Mapping 404 to /index.html with status 200 would therefore rewrite
  # the API's genuine 404s as well, and the frontend would receive HTML where it
  # expected JSON. Verified the hard way: /api/v1/venues/nope returned 200.
  #
  # The SPA fallback is done by a CloudFront Function attached to the default
  # behaviour only. See functions/spa-rewrite.js.

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = { Name = "${var.name_prefix}-cdn" }
}

# --------------------------------------------------------------- bucket policy
# The whole security model in one statement: allow the CloudFront SERVICE to
# read, but only when the request comes from THIS distribution. Another
# distribution in another account signing with OAC gets nothing.
data "aws_iam_policy_document" "site" {
  statement {
    sid       = "AllowCloudFrontServicePrincipalReadOnly"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site.json

  # The public access block must exist first, or S3 can reject a policy it
  # believes might grant public access.
  depends_on = [aws_s3_bucket_public_access_block.site]
}

# ------------------------------------------------------------- placeholder page
# So the URL serves something the moment this applies, before the Frontend team
# has built anything. The deploy pipeline overwrites it on the first real deploy.
resource "aws_s3_object" "placeholder" {
  bucket       = aws_s3_bucket.site.id
  key          = "index.html"
  content_type = "text/html; charset=utf-8"

  content = <<-HTML
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>SportAble Melbourne</title>
      </head>
      <body>
        <h1>SportAble Melbourne</h1>
        <p>Staging environment. The application has not been deployed yet.</p>
        <p>FIT5120 Studio Project - Team Lumera</p>
      </body>
    </html>
  HTML

  # The deploy pipeline replaces this file with the real build. Without this,
  # every `terraform plan` after a deploy would want to put the placeholder
  # back, and eventually someone would let it.
  #
  # `cache_control` is in this list for a sharper reason than the others, found
  # on 1 Sep 2026 by reading a plan that should have been empty:
  #
  #     ~ cache_control = "no-cache,must-revalidate" -> null
  #
  # The pipeline uploads index.html with that header deliberately. It is what
  # stops a browser serving last week's index.html — the one file that must
  # never be cached, because it is the file that names the hashed asset bundles.
  # Terraform does not set it here, so it wanted to REMOVE it, and applying that
  # would have left every returning visitor on a stale build with no error
  # anywhere to explain why.
  lifecycle {
    ignore_changes = [content, etag, content_type, cache_control, metadata, tags]
  }

}

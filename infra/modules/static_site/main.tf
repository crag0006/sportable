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
  comment = "SPA routing${var.basic_auth_credentials == null ? "" : " + basic auth"}"
  publish = true

  # templatefile, not file: the basic-auth credential is injected from a
  # variable so it is never committed. With no credential supplied the auth
  # block is omitted entirely and the function is pure SPA routing.
  code = templatefile("${path.module}/functions/spa-rewrite.js.tftpl", {
    basic_auth_b64   = var.basic_auth_credentials == null ? "" : base64encode(var.basic_auth_credentials)
    basic_auth_realm = var.name_prefix
  })
}

# ------------------------------------------------------ events cache policy
# AC4.2.5 asks for an event page in under three seconds. The events data comes
# from DS-09, which is pulled ONCE A WEEK — so between Sunday runs every
# /api/v1/events response is a function of a database that does not change.
# Sending each one to Lambda, into the VPC, through PostGIS and back is paying
# a cold start and a spatial query over and over for an answer that was
# identical five seconds ago.
#
# None of the managed cache policies fit. CachingOptimized (658327ea) strips
# query strings from the cache key, and /api/v1/events is ALL query string —
# from, to, sport, suburb, postcode, near, radius_m, weekday, time_of_day,
# price, page. With query strings dropped, a search for Saturday swimming in
# Preston would be served the cached answer for a completely different filter
# set. That is not a slow page, it is a wrong one. Hence a policy of our own.
#
# WHAT IS IN THE CACHE KEY, AND WHY NOTHING ELSE IS
#   query strings  all   — they ARE the request; see above.
#   headers        none  — this API varies its body on the path and the query
#                          string and on nothing else. Adding headers to the
#                          key would fragment the cache per browser for no
#                          change in the response.
#   cookies        none  — there is no authentication anywhere in this stack
#                          and no endpoint sets a cookie, so there is no
#                          per-user response that could leak to another viewer.
#                          Revisit this line, first and immediately, if a login
#                          is ever added.
#
# THE TTLs ARE SHORT ON PURPOSE, DESPITE THE WEEKLY REFRESH
#   /api/v1/events defaults `from` to TODAY, computed at the origin. A response
#   cached for a day would, after midnight, still be answering with yesterday's
#   window — and the events epic's whole risk is showing somebody a session
#   that has already happened. Five minutes bounds that error to five minutes
#   past midnight while still collapsing the demo's and the marker's repeated
#   requests onto one origin hit.
#
#   min_ttl stays 0 so the origin keeps the casting vote: a handler that sends
#   Cache-Control: no-store for a response it knows is volatile is obeyed
#   rather than overridden by the edge.
resource "aws_cloudfront_cache_policy" "events_api" {
  name    = "${var.name_prefix}-events-api"
  comment = "Edge cache for /api/v1/events*, keyed on the full query string"

  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 3600

  parameters_in_cache_key_and_forwarded_to_origin {
    # The default_cache_behavior sets compress = true, and so does the events
    # behaviour below. Without these two flags CloudFront would cache one
    # object per encoding variant under a single key and could hand a gzipped
    # body to a client that did not ask for one.
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    query_strings_config {
      query_string_behavior = "all"
    }

    headers_config {
      header_behavior = "none"
    }

    cookies_config {
      cookie_behavior = "none"
    }
  }
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

  # ORDER IS LOAD-BEARING FROM HERE DOWN. CloudFront evaluates ordered cache
  # behaviours in the order they are listed and takes the FIRST pattern that
  # matches — it does not prefer the most specific one. So /api/v1/events*,
  # which is a subset of /api/*, has to be declared first or it would never be
  # reached and every events request would fall through to the CachingDisabled
  # behaviour below. Terraform emits ordered_cache_behavior blocks in the order
  # they appear in this file, which is what makes the rule above something this
  # configuration can rely on. Do not reorder these two blocks.
  #
  # Nothing else changes. /api/v1/venues, /api/v1/venues/search, /api/v1/config
  # and every other route still match /api/* and still reach the origin on
  # every request, with the same cache policy, origin request policy and
  # headers policy they had before. The events routes are read-only GETs over
  # data that refreshes once a week; the venue search is the endpoint the
  # comment below warns about and it is deliberately left alone.
  dynamic "ordered_cache_behavior" {
    for_each = var.api_origin_domain == null ? [] : [1]

    content {
      # Covers /api/v1/events, /api/v1/events/sports, /api/v1/events/{id} and
      # /api/v1/events/{id}.ics — all GETs, all public, all derived from the
      # weekly DS-09 load.
      path_pattern           = "/api/v1/events*"
      target_origin_id       = "apigw"
      viewer_protocol_policy = "redirect-to-https"

      # The same method list as /api/* below, NOT a narrowed GET/HEAD one.
      # Narrowing would make CloudFront answer a future POST /api/v1/events
      # with a 403 MethodNotAllowed that looks like an auth failure and is not.
      # CloudFront never caches anything but GET and HEAD regardless of what is
      # allowed, so the wide list costs nothing and removes a trap.
      allowed_methods = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods  = ["GET", "HEAD"]
      compress        = true

      # Our own policy, defined above. This is the one difference from /api/*.
      cache_policy_id = aws_cloudfront_cache_policy.events_api.id

      # Managed-AllViewerExceptHostHeader, the SAME policy the /api/* behaviour
      # uses, and for the same reason: API Gateway rejects a request whose Host
      # header is not its own domain. It forwards more to the origin than the
      # cache key contains, which is allowed and is the normal shape for an API
      # behind a cache — the narrower key is what makes the cache useful, and
      # the API ignores the cookies and headers it is handed.
      origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"

      response_headers_policy_id = "67f7725c-6f97-4210-82d7-5512b31e9d03"
    }
  }

  # /api/* is evaluated BEFORE the default behaviour, and AFTER the events
  # behaviour above.
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

  # Custom domains, when this environment has them. Each iteration is served
  # from its own distribution on its own domain, so the URL for a submitted
  # iteration keeps showing that iteration after dev has moved on.
  aliases = var.aliases

  viewer_certificate {
    # Exactly one of these two paths applies. With no certificate the
    # distribution keeps the free *.cloudfront.net one, which is what staging
    # uses; with a certificate it serves the aliases above.
    cloudfront_default_certificate = var.acm_certificate_arn == null
    acm_certificate_arn            = var.acm_certificate_arn

    # sni-only, not vip. `vip` dedicates an IP per distribution and costs about
    # USD $600/month; sni-only is free and supported by every browser this
    # project targets.
    ssl_support_method = var.acm_certificate_arn == null ? null : "sni-only"

    # The default when a certificate is attached is TLSv1, which is long
    # obsolete. Set it explicitly rather than inheriting it.
    minimum_protocol_version = var.acm_certificate_arn == null ? null : "TLSv1.2_2021"
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

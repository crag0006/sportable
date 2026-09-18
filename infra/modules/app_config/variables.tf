variable "name_prefix" {
  description = "Prefix for resource Name tags, e.g. \"sportable-staging\"."
  type        = string
}

variable "ssm_prefix" {
  description = <<-EOT
    Parameter Store path prefix, e.g. "/sportable/staging".

    The same prefix the database module writes its credentials under. One tree
    per environment means the API can fetch everything it needs with a single
    GetParametersByPath, and an IAM policy can be scoped with one wildcard.
  EOT
  type        = string
}

variable "distance_bands_m" {
  description = <<-EOT
    Radii offered in the UI, in metres. AC1.2.4 names 250 m, 500 m and 1 km.

    Kept as numbers rather than strings so the precondition below can compare
    them to the default without string/number coercion surprises.
  EOT
  type        = list(number)

  validation {
    condition     = length(var.distance_bands_m) >= 2
    error_message = "At least two bands, or there is nothing for the user to choose between."
  }

  validation {
    # A PostGIS ST_DWithin over a geography column with a radius this large stops
    # being a proximity search and starts being a table scan.
    condition     = alltrue([for b in var.distance_bands_m : b > 0 && b <= 5000])
    error_message = "Each band must be between 1 and 5000 metres."
  }
}

variable "default_distance_m" {
  description = "Radius applied before the user picks one. Must appear in distance_bands_m."
  type        = number
}

variable "max_results" {
  description = <<-EOT
    Cap on venues returned by one search.

    Exists to bound query cost on db.t4g.micro, not to shape the product. If
    the Frontend needs more, raise it here rather than paginating in the client.
  EOT
  type        = number
  default     = 100
}

variable "source_staleness_days" {
  description = <<-EOT
    Days after which each source's data is presented as stale, keyed by the
    source name used in data/ingestion/extractors/.

    Set each one LONGER than its publisher's refresh cadence. Equal thresholds
    mean a single missed refresh — a public holiday, a portal outage — makes the
    UI apologise for data that is fine.

    DS-09 is keyed "aaaplay": that is the extractor module name
    (data/ingestion/extractors/aaaplay.py), the card's retrieval.raw_prefix and
    therefore the S3 prefix the objects land under. Keying it by source id
    would break the one rule this map has, which is that the key is what the
    pipeline already calls the source.
  EOT
  type        = map(number)
}

# ------------------------------------------------------------------------------
# Events (DS-09 / AAA Play)
# ------------------------------------------------------------------------------

variable "events_scope" {
  description = <<-EOT
    Geographic scope the events epic covers, as a plain word the API and the
    interface can both repeat back to the user.

    "victoria", not "greater_melbourne". DS-09 is a statewide publisher and the
    card is explicit that the publisher's own region taxonomy is a reporting
    cut and NEVER a scope boundary — roughly 213 of its 530 activities sit
    outside Greater Melbourne, led by Geelong, Bendigo and Ballarat, and they
    are in scope. This parameter exists so that if scope ever narrows again it
    narrows in one auditable place rather than in a predicate somewhere in a
    query.
  EOT
  type        = string
  default     = "victoria"
}

variable "aaa_play_base_url" {
  description = <<-EOT
    Root of the AAA Play WordPress REST API, without a trailing slash.

    A PARAMETER RATHER THAN A CONSTANT, DELIBERATELY. See the note in main.tf:
    this is an unversioned third-party API we have no agreement with, and the
    day it moves we want a put-parameter, not a release.
  EOT
  type        = string
  default     = "https://www.aaaplay.org.au/wp-json/wp/v2"

  validation {
    # http:// would send the whole pull in clear text over the internet, and a
    # trailing slash turns every joined path into a double slash, which
    # WordPress answers with a redirect at best and a 404 at worst.
    condition     = can(regex("^https://", var.aaa_play_base_url)) && !endswith(var.aaa_play_base_url, "/")
    error_message = "aaa_play_base_url must start with https:// and must not end with a slash."
  }
}

variable "aaa_play_page_size" {
  description = <<-EOT
    WordPress per_page for the DS-09 collection endpoints.

    100 is the maximum the WordPress REST API accepts; asking for more returns
    a 400, not a larger page. At 100 the full pull is eighteen requests. Lower
    it only to be gentler on the publisher — every halving roughly doubles the
    request count for the same bytes.
  EOT
  type        = number
  default     = 100

  validation {
    condition     = var.aaa_play_page_size >= 1 && var.aaa_play_page_size <= 100
    error_message = "aaa_play_page_size must be between 1 and 100 — WordPress rejects per_page above 100."
  }
}

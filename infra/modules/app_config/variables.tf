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
  EOT
  type        = map(number)
}

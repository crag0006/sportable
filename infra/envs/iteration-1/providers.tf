provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "sportable"
      Environment = "iteration-1"
      ManagedBy   = "terraform"
      Owner       = "charan"
      Repository  = "crag0006/sportable"
    }
  }
}

# ------------------------------------------------------------------------------
# A SECOND provider, pinned to us-east-1, for one resource only
# ------------------------------------------------------------------------------
#
# CloudFront reads ACM certificates from us-east-1 and nowhere else, regardless
# of which region the distribution serves or where the buckets live. A
# certificate issued in ap-southeast-2 is simply invisible to it, and the error
# does not mention regions — you get told the certificate does not exist.
#
# Everything else here stays in Sydney.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "sportable"
      Environment = "iteration-1"
      ManagedBy   = "terraform"
      Owner       = "charan"
      Repository  = "crag0006/sportable"
    }
  }
}

# Refuse to run against the wrong account. There are three in play and
# `aws configure` remembers whichever profile was used last.
data "aws_caller_identity" "current" {}

resource "terraform_data" "account_guard" {
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
      error_message = "Wrong AWS account: got ${data.aws_caller_identity.current.account_id}, expected ${var.expected_account_id}. Check AWS_PROFILE."
    }
  }
}

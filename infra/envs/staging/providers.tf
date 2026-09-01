provider "aws" {
  region = var.region

  # Applied to every resource this configuration creates, without a tags block
  # anywhere else. On a shared account this is what answers "which of these is
  # mine?" — and what makes teardown reliable, because you can list everything
  # by tag rather than by memory.
  default_tags {
    tags = {
      Project     = "sportable"
      Environment = "staging"
      ManagedBy   = "terraform"
      Owner       = "charan"
      Repository  = "crag0006/sportable"
    }
  }
}

# Guardrail: refuse to run against the wrong AWS account. There are three in
# play, and `aws configure` remembers whichever profile was used last. This
# turns a catastrophe into an error message.
data "aws_caller_identity" "current" {}

resource "terraform_data" "account_guard" {
  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.expected_account_id
      error_message = "Wrong AWS account: got ${data.aws_caller_identity.current.account_id}, expected ${var.expected_account_id}. Check AWS_PROFILE."
    }
  }
}

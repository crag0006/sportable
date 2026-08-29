# ==============================================================================
# Resource Group — the console view Terraform does not otherwise give you
# ==============================================================================
#
# CloudFormation shows every resource in a stack because CloudFormation is an
# AWS service and owns the stack object. Terraform runs on a laptop; AWS only
# ever sees the individual API calls, so there is nothing for the console to
# display.
#
# A Resource Group is a saved tag query. This one appears under
# Resource Groups → sportable-staging and lists everything this environment
# manages, grouped by service — which is as close to a stack view as Terraform
# gets, and it works for anyone on the account, including the account holder.
#
# It exists only because providers.tf sets default_tags. That one block is what
# stamps Project/Environment onto every resource without a tags argument
# anywhere in the modules.
#
# Free: Resource Groups carry no charge.
#
# CAVEAT — this view is not complete, and cannot be.
#   Route table ASSOCIATIONS, individual ROUTES and security group rule
#   attachments are not taggable resources in AWS, so they never appear here
#   however correct the query is. `terraform state list` remains the
#   authoritative inventory; this is for orientation and for showing others.
#
#   The Resource Groups Tagging API is also an eventually-consistent index
#   rather than a live query. It can lag by minutes, and has been observed
#   listing a subnet that had already been deleted.
# ==============================================================================

resource "aws_resourcegroups_group" "staging" {
  name = local.name_prefix
  # Resource Groups restrict descriptions to [\sa-zA-Z0-9_.-] — no semicolons,
  # no slashes, no commas. An otherwise harmless sentence fails with a 400.
  description = "All resources Terraform manages for SportAble staging. Defined in infra-envs-staging."

  resource_query {
    # TAG_FILTERS_1_0 is the default query type and the only one needed here.
    # The alternative, CLOUDFORMATION_STACK_1_0, is for grouping by stack —
    # which is precisely the thing Terraform does not have.
    type = "TAG_FILTERS_1_0"

    query = jsonencode({
      ResourceTypeFilters = ["AWS::AllSupported"]
      TagFilters = [
        {
          Key    = "Project"
          Values = ["sportable"]
        },
        {
          Key    = "Environment"
          Values = ["staging"]
        },
      ]
    })
  }

  tags = { Name = "${local.name_prefix}-resource-group" }
}

output "resource_group_console_url" {
  description = "Open this to see every tagged resource in one place."
  value       = "https://${var.region}.console.aws.amazon.com/resource-groups/group/${aws_resourcegroups_group.staging.name}?region=${var.region}"
}

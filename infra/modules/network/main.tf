# ==============================================================================
# network — VPC, subnets, routing, security groups, S3 Gateway Endpoint
# ==============================================================================
#
# WHAT THIS BUILDS, AND THE ONE IDEA BEHIND IT
#   The database must be unreachable from the internet. That is achieved not by
#   a firewall rule but by the ABSENCE OF A ROUTE: the private subnets have no
#   0.0.0.0/0 entry in their route table, so no path out exists and none can be
#   created by accident.
#
#   Two things then need special handling:
#     - Your team still has to reach the database  → bastion in a public subnet
#     - In-VPC Lambdas still have to reach S3      → S3 Gateway Endpoint
#
#   The endpoint is the important cost decision. It is a route-table entry, not
#   a server: USD $0/month, versus roughly $40/month in ap-southeast-2 for the
#   NAT Gateway that would otherwise be required — before any data crosses it.
#   NEVER add a NAT Gateway to this project.
# ==============================================================================

# ------------------------------------------------------------------------ VPC
resource "aws_vpc" "this" {
  # checkov:skip=CKV2_AWS_11:VPC flow logs are deferred to Iteration 2. Sending
  #   them to CloudWatch requires an IAM role, and this account's deploy
  #   principal has no iam:CreateRole. An S3 destination avoids that but adds
  #   storage cost and a lifecycle policy for no benefit while the VPC carries
  #   no production traffic. Revisit once the API is serving real requests.
  cidr_block = var.vpc_cidr

  # Required for RDS to get a DNS name, and for the S3 endpoint's private DNS
  # to resolve. Both default to true for a new VPC; stated explicitly because
  # turning either off breaks things in ways that are hard to diagnose.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.name_prefix}-vpc" }
}

# The Internet Gateway costs nothing — only a NAT Gateway does. It is what makes
# the public subnet public, and nothing more.
resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-igw" }
}

# -------------------------------------------------------------------- subnets
resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.public_subnet_cidr
  availability_zone = var.azs[0]

  # Deliberately false. Instances do not get an automatic public IP; the bastion
  # asks for one explicitly. That keeps "is this thing on the internet?" an
  # instance-level decision rather than a property of the subnet.
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name_prefix}-public-${var.azs[0]}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  for_each = { for idx, az in var.azs : az => idx }

  vpc_id            = aws_vpc.this.id
  cidr_block        = var.private_subnet_cidrs[each.value]
  availability_zone = each.key

  tags = {
    Name = "${var.name_prefix}-private-${each.key}"
    Tier = "private"
  }
}

# --------------------------------------------------------------------- routing
# A subnet is "public" ONLY because its route table sends 0.0.0.0/0 to an
# Internet Gateway. There is no public flag anywhere in AWS.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-rt-public" }
}

resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

# No default route here, and there must never be one. Adding a 0.0.0.0/0 entry
# to this table is what would expose the database.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-rt-private" }
}

# Associations are separate resources, and forgetting them is the most common
# VPC bug: an unassociated subnet silently falls back to the VPC's main route
# table, which behaves differently from what you wrote.
resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

# ------------------------------------------------------- S3 Gateway Endpoint
# Adds S3's managed prefix list to the private route table. Traffic to S3 leaves
# over the AWS backbone and never touches the internet. No hourly charge, no
# data charge, no ENI.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = { Name = "${var.name_prefix}-vpce-s3" }
}

data "aws_region" "current" {}

# ------------------------------------------------- the default security group
# Every VPC is created with a default security group that allows unrestricted
# traffic between anything assigned to it. Nothing here uses it — but it exists,
# and a resource created later without an explicit group silently lands in it.
#
# Terraform cannot delete a default security group; AWS will not allow it. What
# this resource does is ADOPT the existing one and strip every rule, so falling
# into it by accident grants nothing. Declaring it with no ingress or egress
# blocks is what removes the rules.
resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-default-sg-DO-NOT-USE" }
}

# ==============================================================================
# Security groups
# ==============================================================================
#
# TWO PROPERTIES THAT SHAPE EVERYTHING BELOW
#
#   1. Allow-only. There are no deny rules. Traffic not matched by an allow rule
#      is dropped. You cannot write "block X" — you write nothing.
#
#   2. Stateful. Allow a request in and its reply is automatically permitted.
#      You never write a return rule, unlike a network ACL.
#
# AND THE IMPORTANT ONE: a rule's source can be ANOTHER SECURITY GROUP rather
# than an IP range. "Anything wearing the lambda badge may reach Postgres" stays
# true no matter what address the Lambda ENI gets today — and it gets a new one
# regularly. An IP-based rule would be wrong within hours.
#
# WHY RULES ARE SEPARATE RESOURCES
#   An inline `ingress {}` block inside aws_security_group makes Terraform treat
#   its rule list as authoritative: it deletes any rule it did not create,
#   including ones added by another module or by hand during an incident. The
#   standalone aws_vpc_security_group_*_rule resources compose properly and are
#   what the AWS provider documentation now recommends.
# ==============================================================================

# --------------------------------------------------------------------- bastion
resource "aws_security_group" "bastion" {
  # checkov:skip=CKV2_AWS_5:Attached by later modules — the bastion instance
  #   (T1), the in-VPC Lambdas (T2/T4) and the RDS instance (T1). This finding
  #   is correct today and disappears as those land; remove the skip then.
  name        = "${var.name_prefix}-bastion-sg"
  description = "Bastion host: SSH from named team addresses only"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-bastion-sg" }

  # Creating the replacement before destroying the old one avoids a dependency
  # deadlock when a rule changes.
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "bastion_ssh" {
  for_each = toset(var.allowed_ssh_cidrs)

  security_group_id = aws_security_group.bastion.id
  description       = "SSH from an approved team address"
  cidr_ipv4         = each.value
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

# The bastion needs outbound access: package updates, and the SSH session's own
# return traffic to the database.
resource "aws_vpc_security_group_egress_rule" "bastion_all" {
  security_group_id = aws_security_group.bastion.id
  description       = "Outbound: OS updates and the tunnel to RDS"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# ---------------------------------------------------------------------- lambda
# No ingress rules at all. Nothing connects TO a Lambda; API Gateway invokes it
# through the Lambda service, not over the network. This group exists purely as
# an identity that the RDS group can name.
resource "aws_security_group" "lambda" {
  # checkov:skip=CKV2_AWS_5:Attached by later modules — the bastion instance
  #   (T1), the in-VPC Lambdas (T2/T4) and the RDS instance (T1). This finding
  #   is correct today and disappears as those land; remove the skip then.
  name        = "${var.name_prefix}-lambda-sg"
  description = "In-VPC Lambda functions: egress to RDS and S3 only"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-lambda-sg" }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_egress_rule" "lambda_to_rds" {
  security_group_id            = aws_security_group.lambda.id
  description                  = "PostgreSQL to the database"
  referenced_security_group_id = aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# S3 traffic leaves via the Gateway Endpoint, but a security group still has to
# permit it. The managed prefix list is the correct target: it resolves to
# S3's current address ranges in this region and updates itself.
resource "aws_vpc_security_group_egress_rule" "lambda_to_s3" {
  security_group_id = aws_security_group.lambda.id
  description       = "HTTPS to S3 via the Gateway Endpoint"
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# ------------------------------------------------------------------------- rds
resource "aws_security_group" "rds" {
  # checkov:skip=CKV2_AWS_5:Attached by later modules — the bastion instance
  #   (T1), the in-VPC Lambdas (T2/T4) and the RDS instance (T1). This finding
  #   is correct today and disappears as those land; remove the skip then.
  name        = "${var.name_prefix}-rds-sg"
  description = "PostgreSQL: reachable only from the Lambda and bastion groups"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-rds-sg" }

  lifecycle {
    create_before_destroy = true
  }
}

# Note what is NOT here: no cidr_ipv4, anywhere. The database accepts
# connections from two named groups and from nothing else. There is no IP range
# that reaches it, including from inside the VPC.
resource "aws_vpc_security_group_ingress_rule" "rds_from_lambda" {
  security_group_id            = aws_security_group.rds.id
  description                  = "PostgreSQL from in-VPC Lambda functions"
  referenced_security_group_id = aws_security_group.lambda.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_bastion" {
  security_group_id            = aws_security_group.rds.id
  description                  = "PostgreSQL through the bastion SSH tunnel"
  referenced_security_group_id = aws_security_group.bastion.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

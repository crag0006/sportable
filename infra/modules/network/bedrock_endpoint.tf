# ==============================================================================
# Bedrock interface endpoint — I2
# ==============================================================================
# WHY THIS EXISTS AT ALL
#   The private subnets have one way out: the S3 gateway endpoint. There is no
#   NAT gateway and no default route. Every other AWS API is unreachable from
#   in there, and the failure mode is the nasty one — an SDK call does not get
#   a connection error, it HANGS until the function times out. We have now hit
#   that twice, with SSM and with lambda:InvokeFunction, and both cost a day.
#
#   Bedrock is an AWS API like any other, so the assistant cannot call it from
#   inside the VPC without this.
#
# WHY NOT RUN THE ASSISTANT OUTSIDE THE VPC INSTEAD
#   That would be free — the fetch Lambda already does it. But the assistant
#   has to read venues and events, and from outside the VPC that means calling
#   our own public API over the internet and back, which adds latency and makes
#   the assistant compete with real users for the API Gateway throttle. Paying
#   for the endpoint keeps it inside, reading PostgreSQL directly through the
#   repository layer that is already written and already tested.
#
# WHAT IT COSTS
#   Interface endpoints are billed per availability zone per hour, roughly
#   USD $7.30/month per AZ, plus a trivial per-GB charge on text payloads.
#   Deliberately provisioned in ONE subnet, not both: the Lambdas only ever run
#   in private subnet A, so a second ENI would double the bill for nothing.
#
# OFF BY DEFAULT
#   prod and iteration-1 call this module too and neither runs an assistant.
#   The flag keeps the charge where the feature is.
# ==============================================================================

resource "aws_security_group" "bedrock_endpoint" {
  count = var.enable_bedrock_endpoint ? 1 : 0

  name        = "${var.name_prefix}-bedrock-vpce-sg"
  description = "Bedrock interface endpoint: HTTPS from the in-VPC Lambdas only"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.name_prefix}-bedrock-vpce-sg" }

  lifecycle {
    create_before_destroy = true
  }
}

# The endpoint ENI accepts 443 from the Lambda group and from nothing else. Not
# a CIDR: the Lambda ENI's address changes regularly, so an address-based rule
# would be wrong within hours.
resource "aws_vpc_security_group_ingress_rule" "bedrock_endpoint_from_lambda" {
  count = var.enable_bedrock_endpoint ? 1 : 0

  security_group_id            = aws_security_group.bedrock_endpoint[0].id
  description                  = "HTTPS from the in-VPC Lambda functions"
  referenced_security_group_id = aws_security_group.lambda.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

# The other half. The Lambda group is allow-only and currently permits exactly
# two destinations — 5432 to RDS and 443 to the S3 prefix list. Without this
# rule the call hangs rather than failing, which is the whole trap described at
# the top of this file.
resource "aws_vpc_security_group_egress_rule" "lambda_to_bedrock" {
  count = var.enable_bedrock_endpoint ? 1 : 0

  security_group_id            = aws_security_group.lambda.id
  description                  = "HTTPS to Bedrock via the interface endpoint"
  referenced_security_group_id = aws_security_group.bedrock_endpoint[0].id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  count = var.enable_bedrock_endpoint ? 1 : 0

  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.bedrock-runtime"
  vpc_endpoint_type = "Interface"

  # One subnet, one ENI, one AZ's worth of charge. See the header.
  subnet_ids         = [aws_subnet.private[var.azs[0]].id]
  security_group_ids = [aws_security_group.bedrock_endpoint[0].id]

  # THE SETTING PEOPLE FORGET. With private DNS off, boto3 resolves the public
  # bedrock-runtime hostname, the packet has nowhere to go, and the call hangs
  # until the Lambda timeout. With it on, the normal hostname resolves to the
  # ENI inside the VPC and no client code has to know the endpoint exists.
  private_dns_enabled = true

  tags = { Name = "${var.name_prefix}-vpce-bedrock-runtime" }
}

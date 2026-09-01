# ==============================================================================
# bastion — the only way in to a database that has no public address
# ==============================================================================
#
# WHY THIS EXISTS
#   T1's whole design is that the private subnets have no route to the internet,
#   so RDS cannot be reached from outside the VPC. That is correct, and it also
#   means your Data team cannot reach it either.
#
#   The bastion is a tiny host in the PUBLIC subnet. You SSH to it and forward a
#   local port through that session to RDS. Nothing about the database becomes
#   public; the SSH session is the tunnel.
#
#       ssh -i ~/.ssh/sportable -L 5433:<rds-address>:5432 ec2-user@<bastion-ip>
#
#   With that open, localhost:5433 IS the staging database — the same port the
#   local Docker container uses, so DATABASE_URL is identical either way. Stop
#   the container first or the port is taken.
#
# WHY NOT SSM SESSION MANAGER
#   Session Manager is the modern answer and needs no public IP or SSH key. It
#   requires an IAM instance profile, and the deploy principal on this account
#   has no iam:CreateRole. So this is blocked rather than declined.
#
#   Reaching a private instance through Session Manager would also need three
#   interface VPC endpoints at roughly USD $21/month. The bastion plus an
#   Internet Gateway costs about $8.
#
# COST — roughly USD $8/month running
#   t4g.nano          ~$4/month
#   public IPv4       ~$3.60/month (charged on every public address since 2024)
#   8 GB gp3          ~$0.80/month
#
#   Stop it when you finish for the day:
#       aws ec2 stop-instances --instance-ids <id>
#   Note the public IP CHANGES on every stop/start — see the outputs for how to
#   fetch the current one.
# ==============================================================================

# The current Amazon Linux 2023 AMI, from AWS's own public SSM parameter.
# Hardcoding an AMI id means shipping a machine image that is out of date the
# week after you write it, and ids differ per region.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-${var.ami_architecture}"
}

resource "aws_key_pair" "bastion" {
  key_name   = "${var.name_prefix}-bastion"
  public_key = var.ssh_public_key

  tags = { Name = "${var.name_prefix}-bastion-key" }
}

resource "aws_instance" "bastion" {
  # checkov:skip=CKV_AWS_88:A bastion without a public address cannot be reached
  #   and serves no purpose. This is the ONE host in the design that is meant to
  #   be on the internet, and it is reachable on port 22 from named team
  #   addresses only — never 0.0.0.0/0, which the network module rejects with a
  #   validation rule.
  # checkov:skip=CKV_AWS_126:Detailed (1-minute) CloudWatch monitoring is a paid
  #   feature. A bastion that is stopped most of the day does not warrant it;
  #   the 5-minute default metrics are enough to see it is alive.
  # checkov:skip=CKV2_AWS_41:An IAM instance profile would be the right way to
  #   grant this host anything. The deploy principal has no iam:CreateRole on
  #   this account, so the bastion carries no role and needs none — it forwards
  #   TCP and nothing else.
  ami           = data.aws_ssm_parameter.al2023.value
  instance_type = var.instance_type
  key_name      = aws_key_pair.bastion.key_name

  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]

  # The public subnet sets map_public_ip_on_launch = false deliberately, so
  # "is this on the internet?" is an instance-level decision. This is the one
  # host where the answer is yes.
  associate_public_ip_address = true

  # Nitro-based instances such as t4g are EBS-optimised by default and the flag
  # carries no extra charge, so state it rather than relying on the default.
  ebs_optimized = true

  # IMDSv2 only. Without this, a server-side request forgery bug in anything
  # running here could read instance credentials over plain HTTP. Requiring a
  # session token closes that whole class of attack.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true

    tags = { Name = "${var.name_prefix}-bastion-root" }
  }

  # A psql client on the host, so you can test the database directly from the
  # bastion before trusting the tunnel. Client 15 talks to a server 16 happily.
  user_data = <<-EOT
    #!/bin/bash
    dnf -y update
    dnf -y install postgresql15
  EOT

  # Changing user_data on an existing instance would otherwise be silently
  # ignored — it only runs at first boot. This makes Terraform replace the
  # instance instead, which is the honest behaviour for a disposable host.
  user_data_replace_on_change = true

  tags = { Name = "${var.name_prefix}-bastion" }

  lifecycle {
    # A STOPPED instance releases its auto-assigned public IP, and AWS then
    # reports associate_public_ip_address as false. Terraform sees drift from
    # the configured `true`, and because that attribute can only change by
    # replacement, every plan taken while the bastion is stopped proposes
    # DESTROYING AND RECREATING IT.
    #
    # Since we stop this host every evening to save ~USD $8/month, that would be
    # a destroy in almost every plan — which is exactly how people learn to stop
    # reading plans.
    #
    # The attribute matters at launch and not afterwards, so ignore it. If the
    # instance ever needs to stop being public, change it here and taint the
    # instance deliberately.
    #
    # `ami` is ignored for a related but separate reason, and this one cost us
    # something before it was noticed. The AMI comes from AWS's "latest"
    # public SSM parameter, so its value CHANGES whenever AWS publishes a new
    # Amazon Linux image. `ami` can only change by replacement, so the next
    # apply — whatever it was actually for — silently destroyed the bastion and
    # built a new one.
    #
    # Observed 1 Sep 2026: a deploy of a FRONTEND change replaced the bastion
    # (i-0960d1df… became i-0571788b…) and left it RUNNING. Three consequences,
    # none of them obvious from the plan's summary line:
    #   - it runs, and bills, until somebody notices
    #   - its public IP changes, so every saved tunnel command breaks
    #   - it happened during a deploy that had nothing to do with it
    #
    # A jump host does not need the newest image mid-iteration. To rebuild it
    # deliberately, on purpose, when you actually want a fresh image:
    #   terraform apply -replace='module.bastion.aws_instance.bastion'
    ignore_changes = [associate_public_ip_address, ami]
  }
}

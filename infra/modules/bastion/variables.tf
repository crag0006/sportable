variable "name_prefix" {
  description = "Prefix for resource names, e.g. \"sportable-staging\"."
  type        = string
}

variable "subnet_id" {
  description = "The PUBLIC subnet. A bastion in a private subnet is unreachable and pointless."
  type        = string
}

variable "security_group_id" {
  description = "The bastion security group: SSH from named team addresses only."
  type        = string
}

variable "instance_type" {
  description = <<-EOT
    t4g.micro: Graviton (arm64), ~USD $6/month running. A bastion forwards TCP
    and needs no CPU, so this is oversized already.

    NOT t4g.nano, which would be cheaper but which this account cannot launch:

        InvalidParameterCombination: The specified instance type is not
        eligible for Free Tier.

    Account 725699850301 is on the AWS **Free plan**, which restricts which
    instance types may run at all — a capability limit, not a cost one. The
    eligible set on 29 Aug 2026 was t4g.micro, t4g.small, t3.micro, t3.small,
    c7i-flex.large and m7i-flex.large.

    Re-check the current list with:
        aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true \
          --query 'InstanceTypes[].[InstanceType,ProcessorInfo.SupportedArchitectures[0]]' --output table

    If you switch to a t3 type, ami_architecture must change to "x86_64" — the
    AMI has to match the CPU.
  EOT
  type        = string
  default     = "t4g.micro"
}

variable "ami_architecture" {
  description = "Must match instance_type: arm64 for t4g, x86_64 for t3."
  type        = string
  default     = "arm64"

  validation {
    condition     = contains(["arm64", "x86_64"], var.ami_architecture)
    error_message = "ami_architecture must be arm64 or x86_64."
  }
}

variable "ssh_public_key" {
  description = <<-EOT
    Your SSH PUBLIC key, the full contents of the .pub file.

    Generate one if you have not:
        ssh-keygen -t ed25519 -f ~/.ssh/sportable -C "sportable-bastion"
        cat ~/.ssh/sportable.pub

    A public key is not a secret — it is safe in this repository and in the
    tfvars file. The private half never leaves your machine.
  EOT
  type        = string
}

variable "root_volume_size" {
  description = "GB. 8 is ample: this host runs sshd and nothing else."
  type        = number
  default     = 8
}

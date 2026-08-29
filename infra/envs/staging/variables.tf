variable "region" {
  description = "Everything lives in Sydney."
  type        = string
  default     = "ap-southeast-2"
}

variable "expected_account_id" {
  description = "The team account. Any other id aborts the plan — see providers.tf."
  type        = string
  default     = "725699850301"
}

variable "allowed_ssh_cidrs" {
  description = <<-EOT
    Public addresses permitted to SSH to the bastion, each as a /32.

    Residential IPs change. When you are locked out, update this list and
    re-apply — never widen it to 0.0.0.0/0.
  EOT
  type        = list(string)
}

variable "ssh_public_key" {
  description = <<-EOT
    SSH public key authorised on the bastion.

    Generate one if you have not:
        ssh-keygen -t ed25519 -f ~/.ssh/sportable -C "sportable-bastion"
        cat ~/.ssh/sportable.pub

    Public keys are not secrets. This one is committed in terraform.tfvars on
    purpose — the private half never leaves your machine.
  EOT
  type        = string
}

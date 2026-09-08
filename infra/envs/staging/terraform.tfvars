# Team members' public addresses, for bastion SSH.
#
# These are residential IPs and will change. When you are locked out, run
#   curl -s https://checkip.amazonaws.com
# add the new /32 here, and re-apply. Never widen to 0.0.0.0/0 — the module
# has a validation rule that rejects it.
allowed_ssh_cidrs = [
  "110.148.190.230/32", # charan, home
  "130.194.14.26/32",   # charan, Monash campus — added 1 Sep 2026 to load the database
]

# SSH public key authorised on the bastion. Public keys are not secrets — the
# private half lives only in ~/.ssh/sportable on Charan's machine.
#
# Add a teammate by appending their key to a second bastion key pair, or by
# adding their public key to ~/.ssh/authorized_keys on the host itself.
ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPZ5OcQLeUyiYDt7LQW7rGMpHsJFQpqBYAM4CuGSgHFc sportable-bastion"

# Alarm mail. Add teammates only if they have agreed to receive it — unwanted
# alarm mail gets filtered, and a filtered alarm is the same as no alarm.
# Each new address must click the confirmation link before it receives anything.
alert_emails = ["crag0006@student.monash.edu"]

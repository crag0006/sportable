# Team members' public addresses, for bastion SSH.
#
# These are residential IPs and will change. When you are locked out, run
#   curl -s https://checkip.amazonaws.com
# add the new /32 here, and re-apply. Never widen to 0.0.0.0/0 — the module
# has a validation rule that rejects it.
allowed_ssh_cidrs = [
  "110.148.190.230/32", # charan
]

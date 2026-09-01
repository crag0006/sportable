# ==============================================================================
# tflint — SportAble Melbourne
# ==============================================================================
#
# WHAT TFLINT ADDS OVER `terraform validate`
#   `terraform validate` checks that the HCL is internally consistent: correct
#   syntax, arguments that exist, types that line up. It does not know anything
#   about AWS. It will happily accept `instance_type = "t4g.mikro"` or an RDS
#   argument that was removed two provider versions ago.
#
#   tflint's AWS ruleset does know. It catches invalid instance types, invalid
#   region names, deprecated arguments and missing required fields — the class
#   of error that otherwise surfaces halfway through `terraform apply`, after
#   some resources already exist.
#
# THE ONE THING TO REMEMBER
#   The AWS rules are NOT bundled. Out of the box tflint only carries its
#   generic Terraform ruleset. The `plugin "aws"` block below is what makes it
#   useful, and `tflint --init` is what downloads it.
#
# USAGE
#   tflint --init                        once per machine (and once per CI run)
#   tflint --recursive --chdir=infra     lint every module and environment
#   tflint --version                     should list `ruleset.aws`
# ==============================================================================

# The bundled ruleset. "recommended" enables naming conventions, unused
# declarations, deprecated interpolation syntax and required version checks.
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

# The AWS provider ruleset — the reason this file exists.
#
# The version is pinned on purpose. An unpinned ruleset silently upgrades, and
# a pipeline that starts failing on a morning when nobody changed anything is
# the most confusing kind of failure to debug. Bump it deliberately, in its own
# commit, and keep this in step with the `tflint_version` in ci.yml.
plugin "aws" {
  enabled = true
  version = "0.48.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

config {
  # How far tflint follows `module` blocks.
  #   "local" — inspect modules stored in this repository (infra/modules/*)
  #   "all"   — also download and inspect registry modules
  #   "none"  — do not follow module calls at all
  #
  # "local" is right here: we write our own modules and want them linted, but
  # we do not want CI reaching out to the Terraform registry on every run.
  call_module_type = "local"
}

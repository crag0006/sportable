#!/usr/bin/env bash
# =============================================================================
# Build the Lambda deployment packages.
#
# Run this before terraform, in CI and by hand alike. The ingestion module
# points at data/build/{fetch,load,derive} and Terraform will not build them
# for you — a plan against a missing directory fails with "source_dir does not
# exist", which is the correct and least confusing failure.
#
#   ./scripts/build_lambda.sh
#
# WHY --platform AND --only-binary
#   pip on Windows or macOS resolves wheels for the machine it is running on.
#   psycopg's binary wheel is platform specific, so a package built on a laptop
#   and uploaded to Lambda imports fine locally and fails at runtime with an
#   undefined symbol. Forcing the manylinux platform makes the laptop build and
#   the CI build produce the same bytes.
# =============================================================================

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$(dirname "$HERE")"
BUILD_DIR="$DATA_DIR/build"

PY_VERSION="3.12"
PLATFORM="manylinux2014_x86_64"

echo "==> Building into $BUILD_DIR"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{fetch,load,derive}

pip_install() {
  local target="$1"; shift
  pip install \
    --target "$target" \
    --platform "$PLATFORM" \
    --python-version "$PY_VERSION" \
    --only-binary=:all: \
    --upgrade \
    --quiet \
    "$@"
}

# -----------------------------------------------------------------------------
# fetch — outside the VPC, talks to publishers and S3 only
# -----------------------------------------------------------------------------
# boto3 ships with the runtime and is deliberately not bundled: a second copy
# inflates the artefact and drifts from whatever the runtime is patched to.

echo "==> fetch"
cp "$DATA_DIR/ingestion/extractors/handler.py" "$BUILD_DIR/fetch/"

# handler.py resolves REGISTER_DIR to /var/task/sources. The source cards are
# the register; without them every invocation fails with "No source card found".
mkdir -p "$BUILD_DIR/fetch/sources"
cp "$DATA_DIR"/sources/*.yaml "$BUILD_DIR/fetch/sources/"

pip_install "$BUILD_DIR/fetch" PyYAML==6.0.2

# -----------------------------------------------------------------------------
# load — inside the VPC, reads S3 and writes RDS
# -----------------------------------------------------------------------------

echo "==> load"
cp "$DATA_DIR/ingestion/loaders/handler.py" "$BUILD_DIR/load/"

mkdir -p "$BUILD_DIR/load/ingestion/transformers" "$BUILD_DIR/load/ingestion/loaders"
touch "$BUILD_DIR/load/ingestion/__init__.py"
touch "$BUILD_DIR/load/ingestion/transformers/__init__.py"
touch "$BUILD_DIR/load/ingestion/loaders/__init__.py"

# DS-01 and DS-02 ONLY, and the empty __init__.py above is why.
#
# ds04 and ds08 take GeoDataFrames and import geopandas at module scope. Copying
# them in would not merely bloat the package — a package __init__ that imports
# them, or an accidental import, fails at cold start with ModuleNotFoundError
# and the failure appears to be about the source being loaded rather than about
# a source that is not. Leaving them out makes the boundary explicit.
#
# The geospatial sources are loaded by hand with scripts/load_run.py through the
# bastion tunnel. They are ABS reference layers republished annually; a weekly
# Lambda would buy nothing and cost a container image build.
cp "$DATA_DIR/ingestion/transformers/ds01_sport_facilities.py" "$BUILD_DIR/load/ingestion/transformers/"
cp "$DATA_DIR/ingestion/transformers/ds02_public_toilets.py" "$BUILD_DIR/load/ingestion/transformers/"
cp "$DATA_DIR/ingestion/loaders/loader.py" "$BUILD_DIR/load/ingestion/loaders/"

mkdir -p "$BUILD_DIR/load/sources"
cp "$DATA_DIR"/sources/*.yaml "$BUILD_DIR/load/sources/"

pip_install "$BUILD_DIR/load" \
  "psycopg[binary]==3.2.3" \
  "pandas==2.2.3" \
  PyYAML==6.0.2

# -----------------------------------------------------------------------------
# derive — inside the VPC, pure SQL against RDS
# -----------------------------------------------------------------------------
# No pandas. The status builder does its work in PostGIS, not in Python, which
# is why this artefact is a tenth the size of the loader.

echo "==> derive"
cp "$DATA_DIR/derive/handler.py" "$BUILD_DIR/derive/"
mkdir -p "$BUILD_DIR/derive/derive"
cp "$DATA_DIR/derive/status_builder.py" "$BUILD_DIR/derive/derive/"
touch "$BUILD_DIR/derive/derive/__init__.py"

pip_install "$BUILD_DIR/derive" "psycopg[binary]==3.2.3"

# -----------------------------------------------------------------------------
# Report
# -----------------------------------------------------------------------------
# Lambda's hard limit is 250 MB unzipped. Printing the sizes here means the
# limit is hit at build time with an obvious cause, rather than at deploy time
# as a RequestEntityTooLarge from the API.

echo
echo "==> Package sizes (Lambda limit: 250 MB unzipped)"
for pkg in fetch load derive; do
  size=$(du -sm "$BUILD_DIR/$pkg" | cut -f1)
  printf "    %-8s %4s MB\n" "$pkg" "$size"
  if [ "$size" -gt 250 ]; then
    echo "    ERROR: $pkg exceeds the Lambda limit. Use a container image."
    exit 1
  fi
done

echo
echo "==> Done."

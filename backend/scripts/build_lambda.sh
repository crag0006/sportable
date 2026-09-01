#!/usr/bin/env bash
# Build the Lambda deployment package for the FastAPI handler.
#
# Produces backend/build/package/ (a directory Terraform's archive_file can zip)
# and backend/build/sportable-api.zip. Dependencies are resolved for the Lambda
# runtime — Python 3.12 on x86_64 manylinux — regardless of the machine this
# runs on, so a build from a Mac or Windows box is identical to one from CI.
#
# Usage:  bash backend/scripts/build_lambda.sh
set -euo pipefail

cd "$(dirname "$0")/.."

rm -rf build/package build/sportable-api.zip
mkdir -p build/package

uv export --no-dev --no-hashes --no-emit-project --format requirements.txt > build/requirements.txt

# boto3/botocore ship in the Lambda runtime; excluding them keeps the package small.
grep -viE '^(boto3|botocore|s3transfer)==' build/requirements.txt > build/requirements.lambda.txt

# manylinux_2_28, not manylinux2014. Lambda's python3.12 runtime is Amazon
# Linux 2023 (glibc 2.34), and some dependencies — greenlet, pulled in by
# SQLAlchemy — no longer publish a manylinux2014 (glibc 2.17) wheel for cp312.
# With the older target, resolution fails outright:
#   "greenlet==3.5.5 has no usable wheels ... requirements are unsatisfiable"
uv pip install \
  --python-platform x86_64-manylinux_2_28 \
  --python-version 3.12 \
  --only-binary :all: \
  --target build/package \
  -r build/requirements.lambda.txt

cp -r app build/package/app
cp handlers/api.py build/package/api.py

find build/package -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd build/package && zip -qr ../sportable-api.zip .)
du -sh build/package build/sportable-api.zip

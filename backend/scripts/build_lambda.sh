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

uv pip install \
  --python-platform x86_64-manylinux2014 \
  --python-version 3.12 \
  --only-binary :all: \
  --target build/package \
  -r build/requirements.lambda.txt

cp -r app build/package/app
cp handlers/api.py build/package/api.py

find build/package -name '__pycache__' -type d -prune -exec rm -rf {} +

(cd build/package && zip -qr ../sportable-api.zip .)
du -sh build/package build/sportable-api.zip

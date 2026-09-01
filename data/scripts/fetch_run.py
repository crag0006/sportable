#!/usr/bin/env python3

"""
Run the fetch against one of three targets.

    --target local    write to a folder on disk, no AWS account needed
    --target s3       run the handler here, write to the real raw bucket
    --target lambda   invoke the deployed function and print what it returns

The handler module is identical in all three. `local` swaps the S3 client for a
folder-backed stub, which is how the pipeline was tested before the account
existed and is still the fastest way to check a source card change offline.
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "data" / "ingestion" / "extractors"))

REGISTER_DIR = ROOT / "data" / "sources"


class LocalS3:
    """Folder-backed stand-in for the S3 client.

    Only the three calls the handler makes are implemented. It deliberately does
    not emulate versioning, encryption or lifecycle, so a local run proves the
    fetch logic and nothing about the storage guarantees.
    """

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self, folder):
        self.folder = folder

    def put_object(self, Bucket, Key, Body, **kwargs):
        file_path = self.folder / Key
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(Body, bytes):
            file_path.write_bytes(Body)
        else:
            file_path.write_text(Body)

    def get_object(self, Bucket, Key):
        file_path = self.folder / Key

        if not file_path.exists():
            raise self.exceptions.NoSuchKey(Key)

        return {"Body": LocalReader(file_path.read_bytes())}


class LocalReader:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


def all_source_ids():
    return sorted(
        yaml.safe_load(Path(file).read_text(encoding="utf-8"))["source_id"]
        for file in glob.glob(str(REGISTER_DIR / "DS-*.yaml"))
    )


def run_lambda(args, source_ids):

    import boto3

    client = boto3.client("lambda", region_name=args.region)

    payload = {"source_ids": source_ids, "force": args.force}

    response = client.invoke(
        FunctionName=args.function,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )

    body = json.loads(response["Payload"].read().decode("utf-8"))

    # A handled exception comes back as a 200 with FunctionError set, so the
    # status code alone is not the result.
    if response.get("FunctionError"):
        print(f"Function error: {body.get('errorType')}")
        print(body.get("errorMessage"))
        return 1

    print(json.dumps(body, indent=2))

    return 1 if body.get("failed") else 0


def run_here(args, source_ids):

    import handler as fetch

    fetch.REGISTER_DIR = REGISTER_DIR

    if args.target == "local":
        output_folder = Path(args.out).resolve()
        output_folder.mkdir(parents=True, exist_ok=True)

        fetch.RAW_BUCKET = "local"
        fetch.s3 = LocalS3(output_folder)

        print(f"Writing to {output_folder}")

    else:
        if not args.bucket:
            print(
                "A bucket is required for --target s3. Get it with `make bucket` or pass --bucket."
            )
            return 2

        fetch.RAW_BUCKET = args.bucket
        output_folder = None

        print(f"Writing to s3://{args.bucket}")

    failed = 0

    for source_id in source_ids:
        print(f"\nProcessing {source_id}...")

        try:
            card = fetch.load_source_card(source_id)
        except Exception as error:
            print(f"{source_id}: could not read source card - {error}")
            failed += 1
            continue

        if card.get("tier") not in fetch.FETCHABLE_TIERS:
            print(f"{source_id}: skipped (tier={card.get('tier')})")
            continue

        try:
            result = fetch.fetch_source(source_id, force=args.force)
        except Exception as error:
            print(f"{source_id}: fetch failed - {type(error).__name__}: {error}")
            failed += 1
            continue

        print(f"{source_id}: {result['outcome']}")

        if result.get("bytes"):
            print(f"Downloaded: {result['bytes']:,} bytes")

        if result.get("sha256"):
            expected = (card.get("retrieval") or {}).get("expected_sha256")

            if expected is None:
                print("SHA-256: no pinned hash")
            elif result["sha256"] == expected:
                print("SHA-256: MATCH")
            else:
                print("SHA-256: DOES NOT MATCH")

            print(f"SHA-256: {result['sha256']}")

        if result.get("manifest_key"):
            if output_folder:
                print(f"Manifest: {output_folder / result['manifest_key']}")
            else:
                print(f"Manifest: s3://{args.bucket}/{result['manifest_key']}")

    return 1 if failed else 0


def main():

    parser = argparse.ArgumentParser(description="Run the SportAble fetch")

    parser.add_argument("source_ids", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--target",
        choices=["local", "s3", "lambda"],
        default="local",
    )
    parser.add_argument("--out", default=str(ROOT / "_raw"))
    parser.add_argument(
        "--bucket",
        help="Raw zone bucket for --target s3",
    )
    parser.add_argument(
        "--function",
        default="sportable-fetch-dev",
        help="Function name for --target lambda",
    )
    parser.add_argument("--region", default="ap-southeast-4")
    parser.add_argument("--force", action="store_true")

    args = parser.parse_args()

    source_ids = args.source_ids

    if args.all:
        source_ids = all_source_ids()

    if not source_ids:
        parser.error("Please provide a source ID, for example DS-01")

    if args.target == "lambda":
        return run_lambda(args, source_ids)

    return run_here(args, source_ids)


if __name__ == "__main__":
    sys.exit(main())

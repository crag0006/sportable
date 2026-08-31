#!/usr/bin/env python3

import argparse
import glob
import sys
from pathlib import Path

import yaml


# Project root
ROOT = Path(__file__).resolve().parents[2]

# Import the fetch handler
sys.path.insert(0, str(ROOT / "data" / "ingestion" / "extractors"))

# Source YAML files
REGISTER_DIR = ROOT / "data" / "sources"


class LocalS3:
    """
    Saves the downloaded files locally instead of uploading them to S3.
    This lets us test the fetch process before setting up AWS.
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


def get_expected_hash(card):
    return (card.get("retrieval") or {}).get("expected_sha256")


def main():

    parser = argparse.ArgumentParser(
        description="Test the data fetch locally"
    )

    parser.add_argument("source_ids", nargs="*")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch all available sources"
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "_raw")
    )
    parser.add_argument(
        "--force",
        action="store_true"
    )

    args = parser.parse_args()

    # Folder where the downloaded files will be stored
    output_folder = Path(args.out).resolve()
    output_folder.mkdir(parents=True, exist_ok=True)

    # Import the actual fetch handler
    import handler as fetch

    # Use our local folder instead of AWS S3
    fetch.RAW_BUCKET = "local"
    fetch.REGISTER_DIR = REGISTER_DIR
    fetch.s3 = LocalS3(output_folder)

    # Decide which datasets to fetch
    source_ids = args.source_ids

    if args.all:
        source_ids = sorted(
            yaml.safe_load(Path(file).read_text())["source_id"]
            for file in glob.glob(
                str(REGISTER_DIR / "DS-*.yaml")
            )
        )

    if not source_ids:
        parser.error("Please provide a source ID, for example DS-01")

    failed = 0

    for source_id in source_ids:

        print(f"\nProcessing {source_id}...")

        # Read the source card
        try:
            card = fetch.load_source_card(source_id)
        except Exception as error:
            print(f"{source_id}: could not read source card - {error}")
            failed += 1
            continue

        # Do not fetch live sources
        if card.get("tier") not in fetch.FETCHABLE_TIERS:
            print(
                f"{source_id}: skipped "
                f"(tier={card.get('tier')})"
            )
            continue

        # Run the fetch
        try:
            result = fetch.handler({
                "source_id": source_id,
                "force": args.force
            })
        except Exception as error:
            print(
                f"{source_id}: fetch failed - "
                f"{type(error).__name__}: {error}"
            )
            failed += 1
            continue

        # Show result
        print(f"{source_id}: {result['outcome']}")

        if result.get("bytes"):
            print(f"Downloaded: {result['bytes']:,} bytes")
        
        # Check SHA-256 if the source card has an expected hash
        if result.get("sha256"):

            expected_hash = get_expected_hash(card)

            if expected_hash is None:
                print("SHA-256: no pinned hash")
            elif result["sha256"] == expected_hash:
                print("SHA-256: MATCH")
            else:
                print("SHA-256: DOES NOT MATCH")

            print(f"SHA-256: {result['sha256']}")
        if result.get("manifest_key"):
            print(
                f"Manifest: "
                f"{output_folder / result['manifest_key']}"
            )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
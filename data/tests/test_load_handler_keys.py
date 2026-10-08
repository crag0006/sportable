"""Tests for the raw object key the load handler is handed.

NO DATABASE AND NO NETWORK. The handler is imported with its required
environment set to throwaway values, because import fails without them and the
function under test touches none of them.

S3 event notifications deliver the object key URL-ENCODED. The raw layout puts
a Hive-style partition in the middle of the key, so every real notification
arrives with `dt=` written as `dt%3D` and nothing in the raw layout tells you
that by reading it. The key the fetch stage writes and the key the load stage
is handed are therefore not the same string, and a parser written against the
first rejects the second.

This is not hypothetical: it took down every S3-triggered load in staging, for
DS-09 and DS-02 alike, with `Unexpected raw key layout: aaaplay/dt%3D...`.
"""

from __future__ import annotations

import os

# Set before the import: handler.py reads these at module level and builds its
# boto3 clients there, so an import with an empty environment raises.
os.environ.setdefault("RAW_BUCKET", "test-raw-bucket")
os.environ.setdefault("SSM_DB_URL_PARAM", "/test/db/url")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

from ingestion.loaders import handler


def test_parse_key_decodes_the_key_as_s3_sends_it() -> None:
    """The encoded form is what arrives in production. It must parse."""
    prefix, dt, filename = handler.parse_key("aaaplay/dt%3D2026-09-15/aaaplay.json")

    assert prefix == "aaaplay"
    assert dt == "2026-09-15"
    assert filename == "aaaplay.json"


def test_parse_key_still_accepts_an_unencoded_key() -> None:
    """The CLI runner passes the key as written in the bucket, undecoded."""
    prefix, dt, filename = handler.parse_key("public_toilets/dt=2026-09-15/toilets.csv")

    assert prefix == "public_toilets"
    assert dt == "2026-09-15"
    assert filename == "toilets.csv"


def test_the_object_is_downloaded_under_its_real_key(monkeypatch) -> None:
    """The key that reaches S3 must be the key that exists in the bucket.

    parse_key alone is not enough: handle_record hands the same string to
    download_file and stores it as load_run.raw_object_key. An encoded key
    there is a 404 and a false provenance record.
    """
    seen: dict[str, str] = {}

    class FakeS3:
        def download_file(self, bucket: str, key: str, dest: str) -> None:
            seen["key"] = key
            # Stop here: what happens after the download is not this test's
            # business, and going further would need a database.
            raise RuntimeError("stop after download")

    monkeypatch.setattr(handler, "s3", FakeS3())

    register = {"aaaplay": {"source_id": "DS-09", "retrieval": {"format": "json"}}}
    record = {"s3": {"object": {"key": "aaaplay/dt%3D2026-09-15/aaaplay.json"}}}

    try:
        handler.handle_record(record, register)
    except RuntimeError as exc:
        assert str(exc) == "stop after download"

    assert seen["key"] == "aaaplay/dt=2026-09-15/aaaplay.json"


def test_parse_key_rejects_a_layout_it_cannot_read() -> None:
    """A key that is not <prefix>/dt=<date>/<file> is still an error.

    Decoding must not turn the check into one that accepts anything: a key
    missing its partition is a fetch-stage bug, and swallowing it here would
    load an object under the wrong date.
    """
    for key in ("aaaplay/aaaplay.json", "aaaplay/2026-09-15/aaaplay.json"):
        try:
            handler.parse_key(key)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {key!r}")

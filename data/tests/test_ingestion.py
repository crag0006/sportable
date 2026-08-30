"""Tests for the two ingestion Lambdas.

These pin the CONTRACT with infrastructure rather than the transforms, because
the transforms do not exist yet and the contract already does:

  - the S3 key convention `<dataset>/dt=YYYY-MM-DD/<filename>`, which
    `infra/modules/ingestion` and `data/README.md` both depend on
  - the manifest shape, which is how anyone tells whether a scheduled run
    actually did anything
  - that a misconfigured fetch FAILS rather than quietly succeeding

They also let the `Data — lint, type-check, test` CI job go green. pytest exits
with code 5 — a failure — when it collects nothing, so a package with handlers
and no tests would turn that job red.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from ingestion import fetch, load


class FakeS3:
    """Minimal stand-in for the S3 client.

    Hand-written rather than moto: three methods are needed, and a fake whose
    behaviour is visible on one screen beats a dependency whose behaviour is
    not.
    """

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects: dict[str, bytes] = objects or {}
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        body = self.objects[Key]

        class _Body:
            @staticmethod
            def read() -> bytes:
                return body

        return {"Body": _Body()}


def _s3_event(key: str, bucket: str = "raw-bucket") -> dict[str, Any]:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


# ------------------------------------------------------------------ fetch
def test_fetch_rejects_an_event_with_no_dataset():
    with pytest.raises(ValueError, match="dataset"):
        fetch.handler({}, None)


def test_fetch_fails_loudly_when_a_source_has_no_url():
    """A scheduled fetch that quietly does nothing is how a pipeline looks
    healthy for a fortnight while the database stays empty."""
    with pytest.raises(ValueError, match="no URL configured"):
        fetch.handler({"dataset": "not_configured_yet"}, None)


def test_fetch_writes_the_agreed_key_convention(monkeypatch):
    """`<dataset>/dt=YYYY-MM-DD/<filename>`.

    infra/modules/ingestion and data/README.md both encode this. Change it in
    one place and the load Lambda stops finding the dataset name.
    """
    fake = FakeS3()
    monkeypatch.setattr(fetch, "_RAW_BUCKET", "raw-bucket")
    monkeypatch.setattr(fetch.boto3, "client", lambda _: fake)

    class _Response:
        headers: ClassVar[dict[str, str]] = {"Content-Type": "application/json"}

        @staticmethod
        def read() -> bytes:
            return b'{"features": []}'

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda *a, **k: _Response())

    result = fetch.handler(
        {"dataset": "public_toilets_nptm", "url": "https://example.test/toilets.geojson"},
        None,
    )

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    assert result["key"] == f"public_toilets_nptm/dt={today}/toilets.geojson"
    assert fake.puts[0]["Metadata"]["dataset"] == "public_toilets_nptm"


def test_fetch_bounds_its_http_call():
    """The lesson from the API's config timeout: a hang is not an exception.

    If this constant is ever removed, a slow publisher stops producing a
    readable error and starts producing an opaque Lambda timeout.
    """
    assert 0 < fetch._HTTP_TIMEOUT_SECONDS < 30


# ------------------------------------------------------------------- load
def test_load_ignores_its_own_manifests():
    """Manifests land in the bucket they describe. Without this guard each one
    would retrigger the function, which would write another, forever."""
    fake = FakeS3({"_manifests/x.json": b"{}"})
    load.boto3.client = lambda _: fake  # type: ignore[assignment]
    assert load.handler(_s3_event("_manifests/x.json"), None)["processed"] == 0


def test_load_decodes_url_encoded_keys(monkeypatch):
    """S3 notifications encode keys: a space arrives as "+".

    Using the raw value produces NoSuchKey on any filename that is not plain
    ASCII — a bug that only appears once a real publisher is wired up.
    """
    real_key = "vic_sport_rec/dt=2026-08-30/sport and rec.csv"
    fake = FakeS3({real_key: b"a,b\n1,2\n3,4\n"})
    monkeypatch.setattr(load.boto3, "client", lambda _: fake)

    result = load.handler(_s3_event(real_key.replace(" ", "+")), None)
    assert result["manifests"][0]["key"] == real_key


def test_load_counts_geojson_features(monkeypatch):
    body = json.dumps({"features": [{}, {}, {}]}).encode()
    key = "public_toilets_nptm/dt=2026-08-30/toilets.geojson"
    fake = FakeS3({key: body})
    monkeypatch.setattr(load.boto3, "client", lambda _: fake)

    manifest = load.handler(_s3_event(key), None)["manifests"][0]
    assert manifest["inspection"] == {"format": "geojson", "parses": True, "features": 3}
    assert manifest["dataset"] == "public_toilets_nptm"


def test_load_records_malformed_json_without_failing(monkeypatch):
    """ "This file is not what we expected" belongs in the manifest, not in a
    stack trace. A genuinely broken fetch already failed upstream."""
    key = "osm/dt=2026-08-30/broken.json"
    fake = FakeS3({key: b"{not json"})
    monkeypatch.setattr(load.boto3, "client", lambda _: fake)

    manifest = load.handler(_s3_event(key), None)["manifests"][0]
    assert manifest["inspection"]["parses"] is False


def test_load_does_not_claim_to_have_loaded_rows(monkeypatch):
    """The database write does not exist yet.

    `rows_loaded: 0` and `load_status: pending_loader` are what stop a green
    invocation from implying data reached Postgres. Delete this test only when
    the loader genuinely writes rows.
    """
    key = "ptv_gtfs/dt=2026-08-30/stops.csv"
    fake = FakeS3({key: b"stop_id,stop_name\n1,Flinders\n"})
    monkeypatch.setattr(load.boto3, "client", lambda _: fake)

    manifest = load.handler(_s3_event(key), None)["manifests"][0]
    assert manifest["rows_loaded"] == 0
    assert manifest["load_status"] == "pending_loader"

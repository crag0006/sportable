"""Unit tests for the ingestion and derivation code.

Everything here runs with no network and no database. A test that needs a live
PostGIS container carries the `integration` marker and is excluded from CI's
unit run; see [tool.pytest.ini_options] in pyproject.toml.
"""

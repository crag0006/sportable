"""Ingestion pipeline. Owned by the Data team.

`extractors`, `transformers`, `validators` and `loaders` live below this.

This file is not a formality. CI runs `mypy ingestion derive`, and mypy exits
with an error — not a warning — on a directory containing no Python at all.
Without it, the type-check step fails the moment anything else here does exist.
"""

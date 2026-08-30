"""Derived values computed from loaded data.

Owned by the Data team. `status_builder` (nearest amenity, the 250/500/1000 m
bands, status derivation) and `graph_builder` (Iteration 2) live here.

This file is not a formality: CI runs `mypy ingestion derive`, and mypy fails
outright on a directory containing no Python at all.
"""

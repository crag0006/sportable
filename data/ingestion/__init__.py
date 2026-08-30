"""Ingestion Lambdas and the modules they call.

`fetch` and `load` are the two entry points AWS invokes. Everything else here —
extractors, transformers, validators, loaders — is called by them and is owned
by the Data team.
"""

"""Gateways: adapters for external services the services layer calls.

A gateway sits beside the repositories in the dependency graph (controller
to service to data access) but reads something that is not our database:
here the Bedrock models. Services see only the Protocols in ``protocols``;
tests substitute fakes the way they do for repositories.
"""

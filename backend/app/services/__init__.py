"""Service layer: one use case per public method, between the routes and the data.

Routes parse the request into a query object from ``app.services.inputs`` and
call one service method; services resolve places, read the repositories and
assemble the response model with the pure rules in ``app.domain``. Nothing in
``app.api`` imports a repository, and nothing here imports FastAPI.
"""

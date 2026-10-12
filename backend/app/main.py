"""FastAPI application factory.

Run locally with::

    cd backend
    uv run uvicorn app.main:app --reload --port 8000

with ``DATABASE_URL`` exported (or in ``backend/.env``). In Lambda the same
application is wrapped by Mangum in ``handlers/api.py``.
"""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1.routes import router
from app.core.config import get_settings
from app.core.errors import install_error_handlers


def create_app() -> FastAPI:
    """Build the FastAPI application: routes, error handlers, logging."""
    settings = get_settings()
    # Lambda pre-installs a root handler, which makes basicConfig a no-op and
    # would leave the root logger at WARNING: the assistant's INFO counts
    # (AC6.3.5) never reached CloudWatch on staging. Set the level explicitly.
    logging.basicConfig(level=settings.log_level.upper())
    logging.getLogger().setLevel(settings.log_level.upper())

    app = FastAPI(
        title="SportAble Melbourne API",
        version="0.3.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
    )
    install_error_handlers(app)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        """A plain liveness answer at the site root."""
        return JSONResponse({"status": "ok", "service": "sportable-api"})

    return app


app = create_app()

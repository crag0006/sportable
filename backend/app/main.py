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
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(
        title="SportAble Melbourne API",
        version="0.1.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
    )
    install_error_handlers(app)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "sportable-api"})

    return app


app = create_app()

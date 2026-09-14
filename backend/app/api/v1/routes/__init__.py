"""The /api/v1 router.

Three routers, one prefix. The v0.1 aliases (``/search``, ``/meta/sports``,
``/meta/suburbs``) are registered here and nowhere else, so removing them at
the Iteration 2 freeze is one block, not a hunt.
"""

from fastapi import APIRouter

from app.api.v1.routes import meta, venues
from app.schemas.venues import SearchOut, SportsOut, SuburbsOut

router = APIRouter(prefix="/api/v1")
router.include_router(meta.router)
router.include_router(venues.router)

# ---------------------------------------------------------- v0.1 aliases
router.add_api_route(
    "/search",
    venues.search,
    methods=["GET"],
    response_model=SearchOut,
    response_model_exclude_none=True,
    deprecated=True,
    include_in_schema=False,
)
router.add_api_route(
    "/meta/sports",
    meta.sports,
    methods=["GET"],
    response_model=SportsOut,
    deprecated=True,
    include_in_schema=False,
)
router.add_api_route(
    "/meta/suburbs",
    meta.suburbs,
    methods=["GET"],
    response_model=SuburbsOut,
    deprecated=True,
    include_in_schema=False,
)

__all__ = ["router"]

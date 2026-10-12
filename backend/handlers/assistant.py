"""Lambda entry point for the Access Assistant (Epic 6, contract v0.3 section 8).

The same FastAPI application as the API, wrapped by Mangum, on a second
function with its own timeout and throttle (infra/modules/api/assistant.tf).
API Gateway sends only ``POST /api/v1/assistant`` here, so this function runs
the tool loop in ``app.services.assistant`` and nothing else, while the
error envelope, validation and dependency wiring stay identical to the API's.

Nothing a user types is logged (AC6.3.5): the service logs counts and
categories only, and the framework's own access log carries no body.
"""

from app.main import app
from mangum import Mangum

handler = Mangum(app, lifespan="off")

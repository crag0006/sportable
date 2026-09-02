"""Lambda entrypoint for the FastAPI application.

Replaces ``stub.handler``. The Terraform ``handler`` becomes ``api.handler`` and
the deployment package must contain the ``app`` package plus its dependencies —
see ``scripts/build_lambda.sh``. The archive_file zip of ``handlers/`` alone is
not enough for this module.
"""

from app.main import app
from mangum import Mangum

handler = Mangum(app, lifespan="off")

"""Titan Text Embeddings v2 through the Bedrock runtime."""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Callable
from typing import Any

from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

LOG = logging.getLogger("sportable.derive.embedder")

DEFAULT_MODEL_ID = "amazon.titan-embed-text-v2:0"
DIMENSIONS = 1024

RETRYABLE_CODES = {
    "ThrottlingException",
    "ModelTimeoutException",
    "ServiceUnavailableException",
    "InternalServerException",
}


class EmbeddingError(RuntimeError):
    """The embedding could not be produced. Nothing partial is ever stored."""


class TitanEmbedder:
    def __init__(
        self,
        client: Any = None,
        model_id: str = DEFAULT_MODEL_ID,
        max_attempts: int = 5,
        base_delay: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self.model_id = model_id
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._sleep = sleep

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            # Retries are handled here, so botocore's own are switched off.
            self._client = boto3.client(
                "bedrock-runtime",
                config=Config(
                    retries={"max_attempts": 1, "mode": "standard"},
                    connect_timeout=10,
                    read_timeout=60,
                ),
            )
        return self._client

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            raise ValueError("Cannot embed empty text.")

        body = json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True})

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.invoke_model(
                    modelId=self.model_id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                payload = json.loads(response["body"].read())

            except ClientError as error:
                code = error.response.get("Error", {}).get("Code", "")

                if code in RETRYABLE_CODES and attempt < self.max_attempts:
                    self._backoff(attempt, code)
                    continue

                raise EmbeddingError(f"Bedrock refused the request: {code}") from error

            except (EndpointConnectionError, ReadTimeoutError, ConnectTimeoutError) as error:
                if attempt < self.max_attempts:
                    self._backoff(attempt, type(error).__name__)
                    continue

                raise EmbeddingError(f"Bedrock unreachable: {type(error).__name__}") from error

            return self._validated(payload.get("embedding"))

        raise EmbeddingError("Bedrock retries exhausted.")  # pragma: no cover

    def _backoff(self, attempt: int, reason: str) -> None:
        delay = min(self.base_delay * 2 ** (attempt - 1), 20.0) + random.uniform(0, 0.5)
        LOG.warning("embed attempt %d failed (%s), retrying in %.1fs", attempt, reason, delay)
        self._sleep(delay)

    @staticmethod
    def _validated(vector: Any) -> list[float]:
        if not isinstance(vector, list) or len(vector) != DIMENSIONS:
            got = len(vector) if isinstance(vector, list) else type(vector).__name__
            raise EmbeddingError(f"Expected {DIMENSIONS} dimensions, got {got}.")

        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in vector):
            raise EmbeddingError("Embedding contains a non-numeric value.")

        return [float(x) for x in vector]

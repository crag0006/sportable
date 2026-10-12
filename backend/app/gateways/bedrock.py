"""Bedrock gateways: Claude through the Anthropic SDK's Bedrock client, Titan through boto3.

Both clients are built lazily so importing the app never touches the
network, and both fail as ``ModelUnavailableError`` so the service can answer
``kind: unavailable`` instead of a 500. Nothing from a request is logged here.
"""

import json
import logging
from typing import Any

from app.core.config import Settings
from app.gateways.protocols import ModelReply, ModelUnavailableError, ToolCall

log = logging.getLogger(__name__)
# One model call. The 18 s loop budget plus one call stays under the 29 s gateway cut-off.
CALL_TIMEOUT_S = 10.0


def _aws_kwargs(settings: Settings) -> dict[str, Any]:
    """Region, plus the temporary bridge credentials when infra set them."""
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.bedrock_access_key_id and settings.bedrock_secret_access_key:
        kwargs["aws_access_key_id"] = settings.bedrock_access_key_id
        kwargs["aws_secret_access_key"] = settings.bedrock_secret_access_key
    return kwargs


class BedrockChatModel:
    """``ChatModel`` over ``anthropic.AnthropicBedrock``."""

    def __init__(self, settings: Settings) -> None:
        """Keep the settings; the client is created on first use."""
        self._settings = settings
        self._client: Any = None

    def _get_client(self) -> Any:
        """The SDK client, created once."""
        if self._client is None:
            from anthropic import AnthropicBedrock

            aws = _aws_kwargs(self._settings)
            self._client = AnthropicBedrock(
                aws_region=aws["region_name"],
                aws_access_key=aws.get("aws_access_key_id"),
                aws_secret_key=aws.get("aws_secret_access_key"),
                timeout=CALL_TIMEOUT_S,
                max_retries=1,
            )
        return self._client

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any],
        max_tokens: int,
    ) -> ModelReply:
        """One Messages API call with the system prompt and tool list cached."""
        try:
            resp = self._get_client().messages.create(
                model=self._settings.bedrock_text_model_id,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
            )
        except Exception as exc:
            log.warning("bedrock chat call failed: %s", type(exc).__name__)
            raise ModelUnavailableError(type(exc).__name__) from exc
        return _reply(resp)


def _reply(resp: Any) -> ModelReply:
    """The SDK response as a ``ModelReply``."""
    blocks = [b.model_dump(exclude_none=True) for b in resp.content]
    return ModelReply(
        text="".join(b.text for b in resp.content if b.type == "text"),
        tool_calls=tuple(
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ),
        stop_reason=resp.stop_reason or "",
        content=blocks,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


class TitanEmbeddingModel:
    """``EmbeddingModel`` over Titan Text Embeddings v2, the same call the derive stage makes."""

    DIMENSIONS = 1024

    def __init__(self, settings: Settings) -> None:
        """Keep the settings; the boto3 client is created on first use."""
        self._settings = settings
        self._client: Any = None

    def _get_client(self) -> Any:
        """The ``bedrock-runtime`` client, created once."""
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                config=Config(
                    retries={"max_attempts": 2}, connect_timeout=3, read_timeout=CALL_TIMEOUT_S
                ),
                **_aws_kwargs(self._settings),
            )
        return self._client

    def embed(self, text: str) -> list[float]:
        """The normalised 1024-d vector for one text."""
        body = json.dumps({"inputText": text, "dimensions": self.DIMENSIONS, "normalize": True})
        try:
            resp = self._get_client().invoke_model(
                modelId=self._settings.bedrock_embedding_model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            vector: list[float] = json.loads(resp["body"].read())["embedding"]
        except Exception as exc:
            log.warning("bedrock embedding call failed: %s", type(exc).__name__)
            raise ModelUnavailableError(type(exc).__name__) from exc
        return vector

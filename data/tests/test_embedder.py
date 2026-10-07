import json

import pytest
from botocore.exceptions import ClientError
from derive.embedder import DIMENSIONS, EmbeddingError, TitanEmbedder


class _Body:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data


class _Client:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def invoke_model(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {"body": _Body(outcome)}


def _error(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "InvokeModel")


def _ok(n=DIMENSIONS):
    return {"embedding": [0.1] * n, "inputTextTokenCount": 3}


def _embedder(client):
    return TitanEmbedder(client=client, sleep=lambda _: None)


def test_request_asks_for_1024_normalised():
    client = _Client([_ok()])
    _embedder(client).embed("hello")
    body = json.loads(client.requests[0]["body"])
    assert body == {"inputText": "hello", "dimensions": 1024, "normalize": True}
    assert client.requests[0]["modelId"] == "amazon.titan-embed-text-v2:0"


def test_retries_throttling_then_succeeds():
    client = _Client([_error("ThrottlingException"), _error("ThrottlingException"), _ok()])
    assert len(_embedder(client).embed("hello")) == DIMENSIONS
    assert len(client.requests) == 3


def test_gives_up_after_max_attempts():
    client = _Client([_error("ThrottlingException")] * 5)
    with pytest.raises(EmbeddingError):
        _embedder(client).embed("hello")
    assert len(client.requests) == 5


def test_non_retryable_error_fails_immediately():
    client = _Client([_error("AccessDeniedException")])
    with pytest.raises(EmbeddingError, match="AccessDenied"):
        _embedder(client).embed("hello")
    assert len(client.requests) == 1


def test_wrong_dimension_is_rejected():
    with pytest.raises(EmbeddingError, match="1024"):
        _embedder(_Client([_ok(256)])).embed("hello")


def test_blank_text_rejected():
    with pytest.raises(ValueError):
        _embedder(_Client([])).embed("   ")

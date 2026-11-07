
import json
from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from app.services.embedding_service import (
    BedrockEmbeddingService,
    EmbeddingServiceError,
)


class FakeBedrockClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None

    def invoke_model(self, **kwargs):
        self.request = kwargs

        if self.error:
            raise self.error

        return {
            "body": BytesIO(
                json.dumps(self.response).encode("utf-8")
            )
        }


def create_service(response=None, error=None):
    service = BedrockEmbeddingService.__new__(
        BedrockEmbeddingService
    )

    service.model_id = "amazon.titan-embed-text-v2:0"
    service.region = "us-east-1"
    service.dimensions = 1024
    service.client = FakeBedrockClient(
        response=response,
        error=error,
    )

    return service


def test_generate_embedding_success():
    expected_embedding = [0.1] * 1024

    service = create_service(
        response={"embedding": expected_embedding}
    )

    result = service.generate_embedding("Enterprise RAG chatbot")

    assert len(result) == 1024
    assert result == expected_embedding

    request_body = json.loads(service.client.request["body"])

    assert request_body["inputText"] == "Enterprise RAG chatbot"
    assert request_body["dimensions"] == 1024
    assert request_body["normalize"] is True

    assert (
        service.client.request["modelId"]
        == "amazon.titan-embed-text-v2:0"
    )


def test_reject_empty_text():
    service = create_service()

    with pytest.raises(ValueError):
        service.generate_embedding("   ")


def test_reject_invalid_embedding_dimensions():
    service = create_service(
        response={"embedding": [0.1, 0.2]}
    )

    with pytest.raises(
        EmbeddingServiceError,
        match="Unexpected embedding dimensions",
    ):
        service.generate_embedding("Test document")


def test_handle_bedrock_access_denied():
    error = ClientError(
        {
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "Access denied",
            }
        },
        "InvokeModel",
    )

    service = create_service(error=error)

    with pytest.raises(
        EmbeddingServiceError,
        match="Unable to generate embeddings",
    ):
        service.generate_embedding("Test document")


import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings


class EmbeddingServiceError(RuntimeError):
    """Raised when embedding generation fails."""


class BedrockEmbeddingService:

    def __init__(self):
        settings = get_settings()

        self.region = settings.aws_region
        self.model_id = settings.bedrock_embedding_model_id
        self.dimensions = 1024

        self.client = boto3.client(
            "bedrock-runtime",
            region_name=self.region,
        )

    def generate_embedding(self, text: str) -> list[float]:

        if not text or not text.strip():
            raise ValueError("Input text cannot be empty.")

        if len(text) > 20000:
            raise ValueError("Input text exceeds the service limit.")

        request_body = {
            "inputText": text,
            "dimensions": self.dimensions,
            "normalize": True,
        }

        try:
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(
                response["body"].read()
            )

            embedding = response_body.get("embedding")

            if not isinstance(embedding, list):
                raise EmbeddingServiceError(
                    "Bedrock returned an invalid embedding."
                )

            if len(embedding) != self.dimensions:
                raise EmbeddingServiceError(
                    "Unexpected embedding dimensions."
                )

            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                for value in embedding
            ):
                raise EmbeddingServiceError(
                    "Embedding contains invalid values."
                )

            return [float(value) for value in embedding]

        except (BotoCoreError, ClientError) as exc:
            raise EmbeddingServiceError(
                "Unable to generate embeddings using Amazon Bedrock."
            ) from exc


bedrock_embedding = BedrockEmbeddingService()

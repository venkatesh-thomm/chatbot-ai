
import json
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.services.embedding_service import bedrock_embedding
from app.services.s3_service import s3_storage


class EmbeddingPipelineError(RuntimeError):
    """Raised when S3-to-Bedrock embedding processing fails."""


class EmbeddingPipeline:

    def __init__(self):
        settings = get_settings()
        self.bucket = settings.s3_documents_bucket
        self.region = settings.aws_region

        self.s3_client = boto3.client(
            "s3",
            region_name=self.region,
        )

    def embed_repository_chunks(
        self,
        *,
        owner: str,
        repository: str,
        branch: str,
        max_chunks: int = 1,
    ) -> dict:

        if not self.bucket:
            raise EmbeddingPipelineError(
                "S3_DOCUMENTS_BUCKET is not configured."
            )

        if max_chunks < 1 or max_chunks > 10:
            raise ValueError(
                "max_chunks must be between 1 and 10."
            )

        owner = quote(owner, safe="-_.")
        repository = quote(repository, safe="-_.")
        branch = quote(branch, safe="-_.")

        prefix = (
            f"documents/github/{owner}/{repository}/{branch}/"
        )

        chunks_key = prefix + "processed/chunks.json"
        embeddings_key = prefix + "processed/embeddings.json"

        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket,
                Key=chunks_key,
            )

            chunks_data = json.loads(
                response["Body"].read().decode("utf-8")
            )

        except (BotoCoreError, ClientError, ValueError) as exc:
            raise EmbeddingPipelineError(
                f"Unable to read source chunks from S3: {chunks_key}"
            ) from exc

        chunks = chunks_data.get("chunks", [])

        if not isinstance(chunks, list) or not chunks:
            raise EmbeddingPipelineError(
                "No chunks were found in the S3 document."
            )

        selected_chunks = chunks[:max_chunks]
        embedded_chunks = []

        for chunk in selected_chunks:
            content = chunk.get("page_content", "")
            metadata = chunk.get("metadata", {})

            if not content.strip():
                continue

            vector = bedrock_embedding.generate_embedding(content)

            embedded_chunks.append({
                "page_content": content,
                "metadata": metadata,
                "embedding": vector,
            })

        if not embedded_chunks:
            raise EmbeddingPipelineError(
                "No valid text chunks were available for embedding."
            )

        payload = {
            "repository": f"{owner}/{repository}",
            "branch": branch,
            "embedding_model": bedrock_embedding.model_id,
            "dimensions": bedrock_embedding.dimensions,
            "chunks_processed": len(embedded_chunks),
            "embeddings": embedded_chunks,
        }

        try:
            s3_storage.upload_json(
                embeddings_key,
                payload,
            )
        except Exception as exc:
            raise EmbeddingPipelineError(
                "Unable to save generated embeddings to S3."
            ) from exc

        return {
            "status": "completed",
            "repository": f"{owner}/{repository}",
            "branch": branch,
            "chunks_processed": len(embedded_chunks),
            "dimensions": bedrock_embedding.dimensions,
            "embedding_model": bedrock_embedding.model_id,
            "bucket": self.bucket,
            "embeddings_s3_key": embeddings_key,
        }


embedding_pipeline = EmbeddingPipeline()

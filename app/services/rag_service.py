
from app.services.github_ingestion import (
    github_ingestor,
    GitHubIngestionError,
)
from app.services.s3_service import (
    s3_storage,
    S3StorageError,
)
from app.services.embedding_pipeline import (
    embedding_pipeline,
    EmbeddingPipelineError,
)
from app.services.vector_indexing_pipeline import (
    VectorIndexingPipeline,
)


class ServiceNotConfigured(RuntimeError):
    """Raised when an AWS service is not configured."""


class RAGService:

    def __init__(self):
        self._vector_indexing = None

    def _get_vector_indexing(self):
        if self._vector_indexing is None:
            self._vector_indexing = VectorIndexingPipeline()

        return self._vector_indexing

    def answer(
        self,
        *,
        query: str,
        max_output_tokens: int,
        temperature: float,
        top_p: float,
        top_k: int,
    ) -> dict:
        raise ServiceNotConfigured(
            "RAG retrieval and Bedrock response generation "
            "are not connected yet."
        )

    def ingest(
        self,
        *,
        bucket_name: str | None,
        path: str | None,
        repository_url: str | None,
        branch: str,
    ) -> dict:

        if bucket_name:
            raise ServiceNotConfigured(
                "Direct S3 source ingestion is not implemented yet."
            )

        if not repository_url:
            raise GitHubIngestionError(
                "Provide a GitHub repository URL."
            )

        bucket = s3_storage.bucket_name

        if not bucket:
            raise S3StorageError(
                "Configure S3_DOCUMENTS_BUCKET."
            )

        if embedding_pipeline.bucket != bucket:
            raise ServiceNotConfigured(
                "S3 bucket configuration differs between "
                "the ingestion and embedding services."
            )

        owner, repository = (
            github_ingestor.parse_repository_url(repository_url)
        )

        # 1. Download repository and create document chunks.
        result = github_ingestor.ingest(
            repository_url=repository_url,
            branch=branch,
        )

        # 2. Upload source documents and chunks to S3.
        upload_result = s3_storage.upload_repository_documents(
            owner=owner,
            repository=repository,
            branch=branch,
            documents=result["documents"],
            chunks=result["chunks"],
        )

        # 3. Generate Bedrock embeddings and save them to S3.
        embedding_result = (
            embedding_pipeline.embed_repository_chunks(
                owner=owner,
                repository=repository,
                branch=branch,
                max_chunks=1,
            )
        )

        # 4. Index the embeddings in OpenSearch Serverless.
        indexing_result = self._get_vector_indexing().index_repository(
            bucket_name=bucket,
            repository=f"{owner}/{repository}",
            branch=branch,
        )

        result.pop("documents", None)
        result.pop("chunks", None)

        return {
            **result,
            "status": "completed",
            "storage": "amazon_s3",
            "s3": upload_result,
            "embeddings": embedding_result,
            "vector_indexing": indexing_result,
            "message": (
                "GitHub repository processed, uploaded to S3, "
                "embedded using Bedrock, and indexed in "
                "OpenSearch Serverless."
            ),
        }


rag_service = RAGService()

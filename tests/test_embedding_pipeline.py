
import json
from io import BytesIO

import pytest

from app.services import embedding_pipeline as pipeline_module
from app.services.embedding_pipeline import (
    EmbeddingPipeline,
    EmbeddingPipelineError,
)


class FakeS3Client:
    def __init__(self, chunks):
        self.chunks = chunks

    def get_object(self, **kwargs):
        return {
            "Body": BytesIO(
                json.dumps(self.chunks).encode("utf-8")
            )
        }


def create_pipeline(monkeypatch):
    pipeline = EmbeddingPipeline.__new__(EmbeddingPipeline)

    pipeline.bucket = "venkatesh-dem1"
    pipeline.region = "us-east-1"

    pipeline.s3_client = FakeS3Client({
        "chunks": [
            {
                "page_content": "Enterprise RAG chatbot",
                "metadata": {
                    "source": "github",
                    "repository": "octocat/Hello-World",
                    "file_name": "README",
                    "chunk_number": 1,
                },
            }
        ]
    })

    uploaded = {}

    def fake_upload(key, payload):
        uploaded["key"] = key
        uploaded["payload"] = payload

    monkeypatch.setattr(
        pipeline_module.s3_storage,
        "upload_json",
        fake_upload,
    )

    monkeypatch.setattr(
        pipeline_module.bedrock_embedding,
        "generate_embedding",
        lambda text: [0.1] * 1024,
    )

    return pipeline, uploaded


def test_embedding_pipeline_success(monkeypatch):
    pipeline, uploaded = create_pipeline(monkeypatch)

    result = pipeline.embed_repository_chunks(
        owner="octocat",
        repository="Hello-World",
        branch="master",
        max_chunks=1,
    )

    assert result["status"] == "completed"
    assert result["chunks_processed"] == 1
    assert result["dimensions"] == 1024

    assert uploaded["key"].endswith(
        "processed/embeddings.json"
    )

    embedding = uploaded["payload"]["embeddings"][0]["embedding"]

    assert len(embedding) == 1024
    assert all(isinstance(value, float) for value in embedding)


def test_embedding_pipeline_rejects_invalid_limit(monkeypatch):
    pipeline, _ = create_pipeline(monkeypatch)

    with pytest.raises(ValueError):
        pipeline.embed_repository_chunks(
            owner="octocat",
            repository="Hello-World",
            branch="master",
            max_chunks=11,
        )


def test_embedding_pipeline_rejects_empty_chunks(monkeypatch):
    pipeline, _ = create_pipeline(monkeypatch)

    pipeline.s3_client = FakeS3Client({"chunks": []})

    with pytest.raises(
        EmbeddingPipelineError,
        match="No chunks were found",
    ):
        pipeline.embed_repository_chunks(
            owner="octocat",
            repository="Hello-World",
            branch="master",
        )


def test_embedding_pipeline_skips_empty_text(monkeypatch):
    pipeline, _ = create_pipeline(monkeypatch)

    pipeline.s3_client = FakeS3Client({
        "chunks": [
            {
                "page_content": "   ",
                "metadata": {},
            }
        ]
    })

    with pytest.raises(
        EmbeddingPipelineError,
        match="No valid text chunks",
    ):
        pipeline.embed_repository_chunks(
            owner="octocat",
            repository="Hello-World",
            branch="master",
        )

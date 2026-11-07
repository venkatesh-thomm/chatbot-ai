
from unittest.mock import Mock

import pytest

from app.services.vector_indexing_pipeline import (
    VectorIndexingPipeline,
)


def test_build_s3_key():
    key = VectorIndexingPipeline.build_s3_key(
        "octocat/Hello-World",
        "master",
    )

    assert key == (
        "documents/github/octocat/Hello-World/"
        "master/processed/embeddings.json"
    )


def test_invalid_repository_is_rejected():
    with pytest.raises(ValueError):
        VectorIndexingPipeline.build_s3_key(
            "../invalid",
            "master",
        )


def test_index_repository_calls_opensearch():
    opensearch = Mock()

    opensearch.index_embeddings_from_s3.return_value = {
        "repository": "octocat/Hello-World",
        "branch": "master",
        "indexed": 1,
        "failed": 0,
    }

    pipeline = VectorIndexingPipeline(opensearch_service=opensearch)

    result = pipeline.index_repository(
        bucket_name="venkatesh-dem1",
        repository="octocat/Hello-World",
        branch="master",
    )

    opensearch.index_embeddings_from_s3.assert_called_once_with(
        bucket_name="venkatesh-dem1",
        object_key=(
            "documents/github/octocat/Hello-World/"
            "master/processed/embeddings.json"
        ),
    )

    assert result["indexed"] == 1
    assert result["failed"] == 0

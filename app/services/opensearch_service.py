
import hashlib
import json
import os
from typing import Any

import boto3
from opensearchpy import (
    AWSV4SignerAuth,
    OpenSearch,
    RequestsHttpConnection,
    helpers,
)


class OpenSearchService:
    def __init__(self) -> None:
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.endpoint = (
            os.getenv("OPENSEARCH_ENDPOINT")
            or os.getenv("OPENSEARCH_COLLECTION_ENDPOINT")
        )
        self.index_name = os.getenv(
            "OPENSEARCH_INDEX_NAME",
            "enterprise-rag-chunks",
        )
        self.dimensions = int(
            os.getenv("BEDROCK_EMBEDDING_DIMENSIONS", "1024")
        )

        if not self.endpoint:
            raise ValueError(
                "Set OPENSEARCH_ENDPOINT or OPENSEARCH_COLLECTION_ENDPOINT"
            )

        host = (
            self.endpoint
            .removeprefix("https://")
            .removeprefix("http://")
            .rstrip("/")
        )

        session = boto3.Session()
        credentials = session.get_credentials()

        if credentials is None:
            raise RuntimeError("AWS credentials were not found")

        auth = AWSV4SignerAuth(
            credentials,
            self.region,
            "aoss",
        )

        self.client = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            pool_maxsize=20,
            timeout=60,
        )

    def create_index(self) -> dict[str, Any]:
        if self.client.indices.exists(index=self.index_name):
            return {
                "status": "already_exists",
                "index": self.index_name,
            }

        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                }
            },
            "mappings": {
                "properties": {
                    "chunk_text": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": self.dimensions,
                        "space_type": "cosinesimil",
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss",
                        },
                    },
                    "source": {"type": "keyword"},
                    "repository": {"type": "keyword"},
                    "branch": {"type": "keyword"},
                    "file_name": {"type": "keyword"},
                    "file_path": {"type": "keyword"},
                    "start_index": {"type": "integer"},
                    "chunk_number": {"type": "integer"},
                    "embedding_model": {"type": "keyword"},
                }
            },
        }

        self.client.indices.create(
            index=self.index_name,
            body=index_body,
        )

        return {
            "status": "created",
            "index": self.index_name,
        }

    @staticmethod
    def _document_id(metadata: dict[str, Any]) -> str:
        identity = "|".join(
            [
                str(metadata.get("repository", "")),
                str(metadata.get("branch", "")),
                str(metadata.get("file_path", "")),
                str(metadata.get("chunk_number", "")),
            ]
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def bulk_index_embeddings(
        self,
        embedding_data: dict[str, Any],
        batch_size: int = 100,
    ) -> dict[str, int]:
        declared_dimensions = embedding_data.get("dimensions")

        if declared_dimensions != self.dimensions:
            raise ValueError(
                f"Expected {self.dimensions} dimensions, "
                f"received {declared_dimensions}"
            )

        records = embedding_data.get("embeddings", [])
        actions = []

        for record in records:
            text = record.get("page_content")
            vector = record.get("embedding")
            metadata = record.get("metadata") or {}

            if not text or not isinstance(vector, list):
                raise ValueError("Invalid embedding record")

            if len(vector) != self.dimensions:
                raise ValueError(
                    f"Invalid vector dimensions: {len(vector)}"
                )

            if not all(
                isinstance(value, (int, float)) for value in vector
            ):
                raise ValueError("Embedding contains non-numeric values")

            document = {
                "chunk_text": text,
                "embedding": vector,
                "source": metadata.get("source", ""),
                "repository": metadata.get("repository", ""),
                "branch": metadata.get("branch", ""),
                "file_name": metadata.get("file_name", ""),
                "file_path": metadata.get("file_path", ""),
                "start_index": metadata.get("start_index", 0),
                "chunk_number": metadata.get("chunk_number", 0),
                "embedding_model": embedding_data.get(
                    "embedding_model", ""
                ),
            }

            actions.append(
                {
                    "_op_type": "index",
                    "_index": self.index_name,
                    "_id": self._document_id(metadata),
                    "_source": document,
                }
            )

        if not actions:
            return {"indexed": 0, "failed": 0}

        success, errors = helpers.bulk(
            self.client,
            actions,
            chunk_size=batch_size,
            raise_on_error=False,
            request_timeout=60,
        )

        return {
            "indexed": success,
            "failed": len(errors),
        }

    def index_embeddings_from_s3(
        self,
        bucket_name: str,
        object_key: str,
    ) -> dict[str, Any]:
        s3 = boto3.client("s3", region_name=self.region)

        response = s3.get_object(
            Bucket=bucket_name,
            Key=object_key,
        )

        embedding_data = json.loads(
            response["Body"].read().decode("utf-8")
        )

        self.create_index()

        result = self.bulk_index_embeddings(embedding_data)

        return {
            "repository": embedding_data.get("repository"),
            "branch": embedding_data.get("branch"),
            "index": self.index_name,
            **result,
        }

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if len(query_embedding) != self.dimensions:
            raise ValueError(
                f"Expected {self.dimensions} dimensions, "
                f"received {len(query_embedding)}"
            )

        if not 1 <= top_k <= 100:
            raise ValueError("top_k must be between 1 and 100")

        response = self.client.search(
            index=self.index_name,
            body={
                "size": top_k,
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": query_embedding,
                            "k": top_k,
                        }
                    }
                },
            },
        )

        return [
            {
                "id": hit["_id"],
                "score": hit["_score"],
                **hit["_source"],
            }
            for hit in response["hits"]["hits"]
        ]

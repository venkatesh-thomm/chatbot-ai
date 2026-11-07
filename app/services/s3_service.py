
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings


class S3StorageError(RuntimeError):
    """Raised when an S3 storage operation fails."""


class S3StorageService:
    def __init__(self):
        settings = get_settings()

        self.bucket_name = settings.s3_documents_bucket
        self.region = settings.aws_region

        self.client = boto3.client(
            "s3",
            region_name=self.region,
        )

    @staticmethod
    def _safe_key_part(value: str) -> str:
        value = value.strip()

        if not value or value in {".", ".."}:
            raise ValueError("Invalid S3 key component.")

        return quote(value, safe="-_.")

    def _base_prefix(
        self,
        owner: str,
        repository: str,
        branch: str,
    ) -> str:
        return (
            "documents/github/"
            f"{self._safe_key_part(owner)}/"
            f"{self._safe_key_part(repository)}/"
            f"{self._safe_key_part(branch)}/"
        )

    def upload_json(self, key: str, payload: dict) -> None:
        if not self.bucket_name:
            raise S3StorageError(
                "S3_DOCUMENTS_BUCKET is not configured."
            )

        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
                ContentType="application/json",
                #ServerSideEncryption="AES256",
            )

        except (BotoCoreError, ClientError) as exc:
            raise S3StorageError(
                f"Unable to upload object to S3: {key}"
            ) from exc

    def upload_repository_documents(
        self,
        *,
        owner: str,
        repository: str,
        branch: str,
        documents: list[dict],
        chunks: list[dict],
    ) -> dict:

        prefix = self._base_prefix(owner, repository, branch)

        timestamp = datetime.now(timezone.utc).isoformat()

        uploaded_files = 0

        for document in documents:
            file_path = document["metadata"]["file_path"]

            source_key = (
                prefix + "source/" +
                self._safe_key_part(file_path)
            )

            self.upload_json(
                source_key + ".json",
                {
                    "metadata": document["metadata"],
                    "content": document["page_content"],
                },
            )

            uploaded_files += 1

        self.upload_json(
            prefix + "processed/chunks.json",
            {
                "repository": f"{owner}/{repository}",
                "branch": branch,
                "created_at": timestamp,
                "chunks": chunks,
            },
        )

        self.upload_json(
            prefix + "processed/manifest.json",
            {
                "repository": f"{owner}/{repository}",
                "branch": branch,
                "files_processed": uploaded_files,
                "chunks_created": len(chunks),
                "created_at": timestamp,
            },
        )

        return {
            "bucket": self.bucket_name,
            "prefix": prefix,
            "files_uploaded": uploaded_files,
            "chunks_uploaded": len(chunks),
        }


s3_storage = S3StorageService()

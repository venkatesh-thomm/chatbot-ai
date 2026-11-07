
import json

import pytest
from botocore.exceptions import ClientError

from app.services.s3_service import (
    S3StorageService,
    S3StorageError,
)


class FakeS3Client:
    def __init__(self):
        self.uploads = []

    def put_object(self, **kwargs):
        self.uploads.append(kwargs)


def create_s3_service():
    service = S3StorageService.__new__(S3StorageService)
    service.bucket_name = "venkatesh-dem1"
    service.region = "us-east-1"
    service.client = FakeS3Client()
    return service


def test_upload_json_uses_correct_bucket_and_key():
    service = create_s3_service()

    service.upload_json(
        "documents/test.json",
        {"message": "hello"},
    )

    assert len(service.client.uploads) == 1

    upload = service.client.uploads[0]

    assert upload["Bucket"] == "venkatesh-dem1"
    assert upload["Key"] == "documents/test.json"
    assert upload["ContentType"] == "application/json"

    payload = json.loads(upload["Body"].decode("utf-8"))
    assert payload["message"] == "hello"


def test_upload_repository_documents():
    service = create_s3_service()

    documents = [
        {
            "page_content": "Example Python source code",
            "metadata": {
                "source": "github",
                "repository": "example/project",
                "branch": "main",
                "file_name": "main.py",
                "file_path": "src/main.py",
            },
        }
    ]

    chunks = [
        {
            "page_content": "Example Python source code",
            "metadata": {
                "source": "github",
                "repository": "example/project",
                "branch": "main",
                "file_name": "main.py",
                "file_path": "src/main.py",
                "chunk_number": 1,
            },
        }
    ]

    result = service.upload_repository_documents(
        owner="example",
        repository="project",
        branch="main",
        documents=documents,
        chunks=chunks,
    )

    assert result["bucket"] == "venkatesh-dem1"
    assert result["files_uploaded"] == 1
    assert result["chunks_uploaded"] == 1

    uploads = service.client.uploads

    assert len(uploads) == 3

    keys = [upload["Key"] for upload in uploads]

    assert any("/source/" in key for key in keys)
    assert any(key.endswith("processed/chunks.json") for key in keys)
    assert any(key.endswith("processed/manifest.json") for key in keys)

    manifest_upload = next(
        upload for upload in uploads
        if upload["Key"].endswith("processed/manifest.json")
    )

    manifest = json.loads(
        manifest_upload["Body"].decode("utf-8")
    )

    assert manifest["repository"] == "example/project"
    assert manifest["files_processed"] == 1
    assert manifest["chunks_created"] == 1


def test_upload_json_handles_s3_error():
    service = create_s3_service()

    def fail_upload(**kwargs):
        raise ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access denied",
                }
            },
            "PutObject",
        )

    service.client.put_object = fail_upload

    with pytest.raises(S3StorageError):
        service.upload_json(
            "documents/test.json",
            {"message": "hello"},
        )

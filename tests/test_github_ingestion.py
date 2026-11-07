
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.services.github_ingestion import (
    GitHubDocumentIngestor,
    GitHubIngestionError,
)


def create_test_archive():
    buffer = BytesIO()

    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "sample-repo-main/README.md",
            "# Enterprise RAG Chatbot\nThis is a test document."
        )
        archive.writestr(
            "sample-repo-main/app.py",
            "def hello():\n    return 'Hello World'"
        )
        archive.writestr(
            "sample-repo-main/node_modules/package.js",
            "This should be ignored."
        )
        archive.writestr(
            "sample-repo-main/image.png",
            "Not a supported document."
        )

    return buffer.getvalue()


def test_parse_valid_github_url():
    owner, repository = (
        GitHubDocumentIngestor.parse_repository_url(
            "https://github.com/example/project"
        )
    )

    assert owner == "example"
    assert repository == "project"


def test_reject_invalid_github_url():
    with pytest.raises(GitHubIngestionError):
        GitHubDocumentIngestor.parse_repository_url(
            "https://example.com/project"
        )


def test_extract_supported_documents():
    ingestor = GitHubDocumentIngestor()

    documents = ingestor.extract_documents(
        archive=create_test_archive(),
        owner="example",
        repository="project",
        branch="main",
    )

    assert len(documents) == 2
    assert documents[0]["metadata"]["repository"] == "example/project"
    assert documents[0]["metadata"]["source"] == "github"


def test_ignore_unsupported_and_excluded_files():
    ingestor = GitHubDocumentIngestor()

    documents = ingestor.extract_documents(
        archive=create_test_archive(),
        owner="example",
        repository="project",
        branch="main",
    )

    file_names = [
        document["metadata"]["file_name"]
        for document in documents
    ]

    assert "README.md" in file_names
    assert "app.py" in file_names
    assert "package.js" not in file_names
    assert "image.png" not in file_names


def test_create_chunks_with_metadata(monkeypatch):
    ingestor = GitHubDocumentIngestor()

    monkeypatch.setattr(
        ingestor,
        "download_archive",
        lambda owner, repository, branch: create_test_archive(),
    )

    result = ingestor.ingest(
        repository_url="https://github.com/example/project",
        branch="main",
    )

    assert result["status"] == "prepared"
    assert result["files_processed"] == 2
    assert result["chunks_created"] >= 2

    for chunk in result["chunks"]:
        assert chunk["metadata"]["source"] == "github"
        assert chunk["metadata"]["repository"] == "example/project"
        assert chunk["metadata"]["chunk_number"] >= 1
        assert "file_path" in chunk["metadata"]

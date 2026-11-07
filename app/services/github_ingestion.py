
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from langchain_text_splitters import RecursiveCharacterTextSplitter


SUPPORTED_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml",
    ".html", ".css", ".js", ".ts", ".java", ".go",
    ".sh", ".sql", ".xml", ".toml", ".ini", ".cfg",
}

EXCLUDED_DIRECTORIES = {
    ".git", "node_modules", "venv", ".venv",
    "__pycache__", "dist", "build", ".idea",
}

SUPPORTED_FILENAMES = {
    "README",
    "LICENSE",
    "NOTICE",
    "CHANGELOG",
    "CONTRIBUTING",
    "DOCKERFILE",
    "MAKEFILE",
}

MAX_ARCHIVE_BYTES = 30 * 1024 * 1024
MAX_FILES = 100
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_TEXT_BYTES = 10 * 1024 * 1024


class GitHubIngestionError(RuntimeError):
    """Raised when a GitHub repository cannot be ingested."""


class GitHubDocumentIngestor:
    def __init__(self):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=50,
            add_start_index=True,
        )

    @staticmethod
    def parse_repository_url(repository_url: str) -> tuple[str, str]:
        parsed = urlparse(repository_url.strip())

        if parsed.scheme != "https" or parsed.hostname != "github.com":
            raise GitHubIngestionError(
                "Only HTTPS GitHub repository URLs are supported."
            )

        parts = [part for part in parsed.path.strip("/").split("/") if part]

        if len(parts) != 2:
            raise GitHubIngestionError(
                "Provide a repository URL in the format "
                "https://github.com/owner/repository"
            )

        owner, repository = parts
        repository = repository.removesuffix(".git")

        if not owner or not repository:
            raise GitHubIngestionError("Invalid GitHub repository URL.")

        return owner, repository

    @staticmethod
    def download_archive(owner: str, repository: str, branch: str) -> bytes:
        if not branch or len(branch) > 200:
            raise GitHubIngestionError("Invalid GitHub branch name.")

        if any(ord(char) < 32 for char in branch):
            raise GitHubIngestionError("Invalid characters in branch name.")

        encoded_branch = quote(branch, safe="/")
        url = (
            f"https://codeload.github.com/{owner}/{repository}"
            f"/zip/refs/heads/{encoded_branch}"
        )

        request = Request(
            url,
            headers={"User-Agent": "Enterprise-RAG-Chatbot"},
        )

        try:
            with urlopen(request, timeout=30) as response:
                archive = response.read(MAX_ARCHIVE_BYTES + 1)

            if len(archive) > MAX_ARCHIVE_BYTES:
                raise GitHubIngestionError(
                    "Repository archive exceeds the 30 MB download limit."
                )

            return archive

        except GitHubIngestionError:
            raise
        except Exception as exc:
            raise GitHubIngestionError(
                "Unable to download the GitHub repository. "
                "Check the repository URL, branch, and network access."
            ) from exc

    @staticmethod
    def extract_documents(
        archive: bytes,
        owner: str,
        repository: str,
        branch: str,
    ) -> list[dict]:
        documents = []
        total_text_bytes = 0

        try:
            with ZipFile(BytesIO(archive)) as zip_file:
                for entry in zip_file.infolist():
                    if entry.is_dir():
                        continue

                    if len(documents) >= MAX_FILES:
                        break

                    path = PurePosixPath(entry.filename)

                    # Do not process unsafe or unexpected archive paths.
                    if path.is_absolute() or ".." in path.parts:
                        continue

                    # GitHub archives have a generated root directory.
                    relative_parts = path.parts[1:]
                    if not relative_parts:
                        continue

                    if any(
                        part in EXCLUDED_DIRECTORIES
                        for part in relative_parts
                    ):
                        continue

                    file_path = PurePosixPath(*relative_parts)

                    if (
                      file_path.suffix.lower() not in SUPPORTED_EXTENSIONS
                      and file_path.name.upper() not in SUPPORTED_FILENAMES
                    ):
                        continue

                    if entry.file_size > MAX_FILE_BYTES:
                        continue

                    content = zip_file.read(entry)
                    total_text_bytes += len(content)

                    if total_text_bytes > MAX_TOTAL_TEXT_BYTES:
                        break

                    text = content.decode("utf-8", errors="replace").strip()

                    if not text:
                        continue

                    documents.append({
                        "page_content": text,
                        "metadata": {
                            "source": "github",
                            "repository": f"{owner}/{repository}",
                            "branch": branch,
                            "file_name": file_path.name,
                            "file_path": str(file_path),
                        },
                    })

        except (BadZipFile, OSError) as exc:
            raise GitHubIngestionError(
                "The downloaded GitHub archive is invalid or unreadable."
            ) from exc

        if not documents:
            raise GitHubIngestionError(
                "No supported text documents were found in the repository."
            )

        return documents

    def ingest(self, repository_url: str, branch: str = "main") -> dict:
        owner, repository = self.parse_repository_url(repository_url)

        archive = self.download_archive(owner, repository, branch)

        documents = self.extract_documents(
            archive=archive,
            owner=owner,
            repository=repository,
            branch=branch,
        )

        chunks = []
        for document in documents:
            split_documents = self.splitter.create_documents(
                texts=[document["page_content"]],
                metadatas=[document["metadata"]],
            )

            for index, chunk in enumerate(split_documents, start=1):
                chunk.metadata["chunk_number"] = index
                chunks.append(chunk)

        return {
            "status": "prepared",
            "repository": f"{owner}/{repository}",
            "branch": branch,
            "files_processed": len(documents),
            "chunks_created": len(chunks),
            "documents": documents,
            "storage": "local_processing_only",
            "message": (
                "Documents extracted and chunked successfully. "
                "S3 storage and vector indexing are not connected yet."
            ),
            "chunks": [
                {
                    "page_content": chunk.page_content,
                    "metadata": chunk.metadata,
                }
                for chunk in chunks
            ],
        }


github_ingestor = GitHubDocumentIngestor()

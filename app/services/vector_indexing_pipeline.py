
from urllib.parse import quote

from app.services.opensearch_service import OpenSearchService


class VectorIndexingPipeline:

    def __init__(
        self,
        opensearch_service: OpenSearchService | None = None,
    ):
        self.opensearch = (
            opensearch_service or OpenSearchService()
        )

    @staticmethod
    def build_s3_key(
        repository: str,
        branch: str,
    ) -> str:

        parts = repository.split("/")

        if (
            len(parts) != 2
            or any(
                not part or part in {".", ".."}
                for part in parts
            )
            or not branch
            or branch.startswith("/")
            or any(
                part == ".."
                for part in branch.split("/")
            )
        ):
            raise ValueError(
                "Invalid repository or branch"
            )

        owner = quote(parts[0], safe="-_.")
        repo = quote(parts[1], safe="-_.")
        encoded_branch = quote(branch, safe="-_.")

        return (
            f"documents/github/{owner}/{repo}/"
            f"{encoded_branch}/processed/embeddings.json"
        )

    def index_repository(
        self,
        bucket_name: str,
        repository: str,
        branch: str = "main",
    ) -> dict:

        object_key = self.build_s3_key(
            repository,
            branch,
        )

        return self.opensearch.index_embeddings_from_s3(
            bucket_name,
            object_key,
        )

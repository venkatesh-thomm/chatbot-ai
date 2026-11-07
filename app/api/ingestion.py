
from fastapi import APIRouter, HTTPException

from app.models.schemas import IngestionRequest
from app.services.rag_service import (
    rag_service,
    ServiceNotConfigured,
)
from app.services.github_ingestion import GitHubIngestionError
from app.services.s3_service import S3StorageError

router = APIRouter(prefix="/api", tags=["ingestion"])


@router.post("/load_data", status_code=202)
def load_data(payload: IngestionRequest):

    if not payload.bucket_name and not payload.repository_url:
        raise HTTPException(
            status_code=422,
            detail="Provide bucket_name or repository_url.",
        )

    if payload.bucket_name and payload.repository_url:
        raise HTTPException(
            status_code=422,
            detail="Provide either bucket_name or repository_url, not both.",
        )

    try:
        return rag_service.ingest(
            bucket_name=payload.bucket_name,
            path=payload.path,
            repository_url=payload.repository_url,
            branch=payload.branch,
        )

    except ServiceNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except GitHubIngestionError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except S3StorageError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc
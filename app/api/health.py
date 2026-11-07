from fastapi import APIRouter
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness():
    settings = get_settings()
    return {
        "status": "not_ready_for_rag",  # changes after AWS adapters are configured
        "environment": settings.environment,
        "aws_region": settings.aws_region,
        "dependencies_configured": {
            "s3": bool(settings.s3_documents_bucket),
            "opensearch": bool(settings.opensearch_endpoint),
            "bedrock_llm": bool(settings.bedrock_llm_model_id),
        },
    }

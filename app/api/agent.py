import hmac
import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi import status

from app.agents.graph import AgentPolicyError, DevOpsAgent
from app.agents.planner import PlannerNotConfigured
from app.config import get_settings
from app.models.schemas import AgentExecutionResult, AgentRequest

router = APIRouter(prefix="/api", tags=["agent"])
logger = logging.getLogger(__name__)

@router.post("/agent/run", response_model=AgentExecutionResult)
def run_agent(
    request: AgentRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    settings = get_settings()
    if not settings.devops_agent_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DevOps agent is disabled until DEVOPS_AGENT_API_KEY is configured.",
        )
    if not x_api_key or not hmac.compare_digest(
        x_api_key, settings.devops_agent_api_key
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )

    try:
        agent = DevOpsAgent(region=request.region)
        result = agent.run(
            request.prompt,
            environment=request.environment,
            action=request.action,
            target_instance_id=request.target_instance_id,
            request_region=request.region,
        )
        return result
    except AgentPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlannerNotConfigured as exc:
        logger.warning("DevOps planner is not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DevOps planner is not configured.",
        ) from exc
    except Exception as exc:
        logger.exception("DevOps agent planning failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="DevOps planning failed. Check the service logs.",
        ) from exc

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.agents.graph import DevOpsAgent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/agent",
    tags=["DevOps Agent"],
)

agent = DevOpsAgent()


class AgentRequest(BaseModel):
    request: str = Field(..., min_length=1)


@router.post("/investigate")
async def investigate(request: AgentRequest):
    started_at = time.perf_counter()
    logger.info(
    "Investigation started | Request: %s",
     request.request,
    )
    try:
        result = await run_in_threadpool(
            agent.run,
            request.request,
        )

        elapsed = time.perf_counter() - started_at
        
        logger.info(
            "DevOps investigation completed in %.2f seconds",
            elapsed,
        )

        return {
            "status": result.get("status"),
            "category": result.get("category"),
            "summary": result.get("response"),
            "investigation_plan": result.get(
                "investigation_plan"
            ),
            "required_tools": result.get("required_tools"),
            "risk_level": result.get("risk_level"),
            "findings": result.get("findings", []),
            "analysis": result.get("analysis"),
            "execution_time_seconds": round(elapsed, 2),
        }

    except ValueError as exc:
        logger.warning("Invalid DevOps request: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        logger.exception("DevOps agent investigation failed")
        raise HTTPException(
            status_code=500,
            detail="DevOps investigation failed. Check application logs.",
        )

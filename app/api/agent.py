import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
def investigate(request: AgentRequest):

    try:
        result = agent.run(request.request)

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
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        logger.exception("DevOps agent investigation failed")

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

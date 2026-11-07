from fastapi import APIRouter, HTTPException
from app.models.schemas import ChatRequest
from app.services.rag_service import rag_service, ServiceNotConfigured

router = APIRouter(prefix="/api", tags=["chat"])


def _run_chat(payload: ChatRequest):
    try:
        result = rag_service.answer(
            query=payload.query,
            max_output_tokens=payload.max_output_tokens,
            temperature=payload.temperature,
            top_p=payload.top_p,
            top_k=payload.top_k,
        )
        # Keep the previous API's capitalized response key.
        if isinstance(result, str):
            return {"Response": result}
        if "Response" not in result and "response" in result:
            result["Response"] = result.pop("response")
        return result
    except ServiceNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/get_response")
def private_get_response(payload: ChatRequest):
    # Authentication/authorization will be added before production exposure.
    return _run_chat(payload)


@router.post("/public/get_response")
def public_get_response(payload: ChatRequest):
    # Retained for API compatibility. Do not expose this route publicly until
    # rate limiting, abuse controls and an explicit access policy are added.
    return _run_chat(payload)

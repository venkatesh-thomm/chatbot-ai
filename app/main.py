from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.api import chat, evaluation, health, ingestion, media
from app.api.agent import router as agent_router

from app.core.logging_config import setup_logging

setup_logging()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
   description=(
    "Enterprise RAG chatbot using FastAPI, "
    "Amazon S3, Amazon Bedrock and OpenSearch Serverless."
),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(ingestion.router)
app.include_router(evaluation.router)
app.include_router(media.router)
app.include_router(agent_router)


@app.get("/")
def root():
    return {"application": settings.app_name, "status": "running", "api_docs": "/docs"}

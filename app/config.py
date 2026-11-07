from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Enterprise RAG Chatbot API"
    environment: str = "local"
    aws_region: str = "us-east-1"
    cors_origins: str = "http://localhost:3000,http://localhost:8080"
    # These are resource identifiers, not credentials. They will be populated
    # when the AWS services are provisioned in later phases.
    s3_documents_bucket: str | None = None
    opensearch_endpoint: str | None = None
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    bedrock_llm_model_id: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

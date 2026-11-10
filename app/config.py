
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Enterprise RAG Chatbot API"
    environment: str = "local"
    aws_region: str = "us-east-1"
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    # DevOps agent security
    devops_agent_api_key: str | None = None
    devops_allowed_environment: str = "development"
    devops_allowed_ec2_actions: str = ""
    devops_target_tag_key: str | None = None
    devops_target_tag_value: str | None = None
    devops_kubernetes_namespace: str = "default"

    # Monitoring
    devops_alerts_sns_topic_arn: str | None = None
    devops_monitor_state_table: str | None = None

    # AWS infrastructure
    s3_documents_bucket: str | None = None
    opensearch_endpoint: str | None = None

    # Bedrock configuration
    bedrock_llm_model_id: str = "us.anthropic.claude-sonnet-4-6"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def allowed_ec2_actions(self) -> set[str]:
        return {
            action.strip()
            for action in self.devops_allowed_ec2_actions.split(",")
            if action.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()

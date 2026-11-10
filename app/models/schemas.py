from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationParameters(BaseModel):
    max_output_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    top_p: float = Field(default=0.4, gt=0.0, le=1.0)
    top_k: int = Field(default=40, ge=1, le=500)


class ChatRequest(GenerationParameters):
    query: str = Field(min_length=1, max_length=12000)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    Response: str
    STS_Score: str | None = None
    RougeN_Precission: float | None = None
    RougeN_Recall: float | None = None
    RougeN_Fmessure: float | None = None
    Sentiment_Label: str | None = None
    Sentiment_Score: str | None = None
    sources: list[dict] = Field(default_factory=list)


class IngestionRequest(BaseModel):
    bucket_name: str | None = None
    path: str | None = None
    repository_url: str | None = None
    branch: str = "main"


class EvaluationSTSRequest(BaseModel):
    query: str = Field(min_length=1)
    response: str = Field(min_length=1)


class EvaluationRougeRequest(BaseModel):
    response: str = Field(min_length=1)
    reference: str = Field(min_length=1)


class EvaluationSentimentRequest(BaseModel):
    query: str = Field(min_length=1)
    response: str = Field(min_length=1)


class AgentRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    action: Literal[
        "plan",
        "list_instances",
        "get_instance_cpu",
        "stop_instance",
        "list_pods",
        "check_health",
    ] = "plan"
    environment: str = Field(default="development", min_length=1, max_length=64)
    region: str | None = Field(default=None, min_length=1, max_length=32)
    target_instance_id: str | None = Field(
        default=None,
        pattern=r"^i-[0-9a-fA-F]{8,17}$",
    )

    @model_validator(mode="after")
    def validate_action_arguments(self):
        if self.action in {"get_instance_cpu", "stop_instance"}:
            if not self.target_instance_id:
                raise ValueError(
                    f"target_instance_id is required for {self.action}."
                )
        elif self.target_instance_id:
            raise ValueError(
                f"target_instance_id is not accepted for {self.action}."
            )
        return self


class AgentExecutionResult(BaseModel):
    status: str
    intent: str
    summary: str
    tool_calls: list[dict] = Field(default_factory=list)
    output: dict = Field(default_factory=dict)
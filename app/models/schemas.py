from pydantic import BaseModel, Field, ConfigDict


class GenerationParameters(BaseModel):
    max_output_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    top_p: float = Field(default=0.4, gt=0.0, le=1.0)
    # Kept for compatibility with the previous API contract. The selected
    # Bedrock model may not support top_k; the Bedrock adapter must validate it.
    top_k: int = Field(default=40, ge=1, le=500)


class ChatRequest(GenerationParameters):
    query: str = Field(min_length=1, max_length=12000)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    Response: str
    # Optional fields retained for compatibility with the old response shape.
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


import boto3

from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings


class BedrockChatError(RuntimeError):
    """Raised when Amazon Bedrock response generation fails."""


class BedrockChatService:

    def __init__(self, client=None):

        settings = get_settings()

        self.region = settings.aws_region
        self.model_id = settings.bedrock_llm_model_id

        if not self.model_id:
            raise ValueError(
                "BEDROCK_LLM_MODEL_ID is not configured."
            )

        self.client = client or boto3.client(
            "bedrock-runtime",
            region_name=self.region,
        )

    def generate_response(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1500,
        temperature: float | None = 0.1,
        top_p: float | None = None,
    ) -> dict:

        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        if max_tokens < 1:
            raise ValueError("max_tokens must be greater than zero.")

        inference_config = {
            "maxTokens": max_tokens,
        }

        # Claude Sonnet 4.6 does not allow temperature
        # and topP to be specified together.
        if temperature is not None:
            inference_config["temperature"] = temperature

        elif top_p is not None:
            inference_config["topP"] = top_p

        request = {
            "modelId": self.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"text": prompt}
                    ],
                }
            ],
            "inferenceConfig": inference_config,
        }

        if system_prompt:
            request["system"] = [
                {"text": system_prompt}
            ]

        try:
            response = self.client.converse(**request)

            message = response.get("output", {}).get(
                "message", {}
            )

            content_blocks = message.get("content", [])

            answer = "\n".join(
                block["text"]
                for block in content_blocks
                if isinstance(block, dict) and "text" in block
            )

            if not answer.strip():
                raise BedrockChatError(
                    "Amazon Bedrock returned an empty response."
                )

            return {
                "answer": answer,
                "model_id": self.model_id,
                "stop_reason": response.get("stopReason"),
                "usage": response.get("usage", {}),
            }

        except (ClientError, BotoCoreError) as exc:
            raise BedrockChatError(
                "Unable to generate response using Amazon Bedrock."
            ) from exc

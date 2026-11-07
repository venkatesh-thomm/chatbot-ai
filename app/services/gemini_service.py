
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

class GeminiService:

    def __init__(self, client=None):

        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_id = os.getenv(
            "GEMINI_MODEL",
            "gemini-2.5-flash",
        )

        if client is None and not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        self.client = client or genai.Client(
            api_key=self.api_key
        )

    def generate_response(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.1,
    ) -> dict:

        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty.")

        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config={
                    "system_instruction": system_prompt or "",
                    "max_output_tokens": max_tokens,
                    "temperature": temperature,
                    "response_mime_type": "application/json",
                },
            )

            answer = response.text

            if not answer:
                raise RuntimeError("Gemini returned an empty response.")

            return {
                "answer": answer,
                "model_id": self.model_id,
            }

        except Exception as exc:
            raise RuntimeError(
                f"Gemini response generation failed: {exc}"
            ) from exc
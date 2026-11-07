
from app.services.bedrock_chat_service import BedrockChatService


def main():
    service = BedrockChatService()

    result = service.generate_response(
        system_prompt=(
            "You are a Senior DevOps Engineer. "
            "Provide technically accurate and practical answers."
        ),
        prompt=(
            "Explain how you would investigate an EC2 instance "
            "that is running but unreachable over SSH. "
            "Give five investigation steps."
        ),
        max_tokens=1024,
        temperature=0.2,
    )

    print("\nModel:", result["model_id"])
    print("Stop reason:", result["stop_reason"])
    print("\nAgent response:\n")
    print(result["answer"])
    print("\nToken usage:", result["usage"])


if __name__ == "__main__":
    main()

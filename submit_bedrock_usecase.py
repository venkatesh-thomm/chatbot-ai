import json
import boto3

# Use your actual details
form_data = {
    "companyName": "Individual Developer",
    "companyWebsite": "https://github.com/venkatesh-thomm/chatbot-ai",
    "intendedUsers": "0",
    "industryOption": "Technology",
    "otherIndustryOption": "",
    "useCases": (
        "Developing an AI-powered DevOps agent using Amazon Bedrock "
        "to investigate AWS infrastructure and Kubernetes incidents, "
        "identify potential root causes, and recommend troubleshooting "
        "actions. Initial operations are read-only. Human approval is "
        "required before infrastructure modifications."
    )
}

client = boto3.client(
    "bedrock",
    region_name="us-east-1"
)

try:
    response = client.put_use_case_for_model_access(
        formData=json.dumps(form_data)
    )

    print("Use-case submission successful.")
    print(response)

except Exception as exc:
    print("Submission failed:")
    print(type(exc).__name__)
    print(str(exc))
import json

from app.agents.prompts import DEVOPS_AGENT_SYSTEM_PROMPT
from app.services.gemini_service import GeminiService


class PlannerNotConfigured(RuntimeError):
    """Raised when the planner's model client cannot be initialized."""


class DevOpsPlanner:

    def __init__(self, gemini_service=None):
        try:
            self.gemini = gemini_service or GeminiService()
        except ValueError as exc:
            raise PlannerNotConfigured(
                "Configure GEMINI_API_KEY to enable DevOps planning."
            ) from exc

    def create_plan(self, request: str) -> dict:

        if not request or not request.strip():
            raise ValueError("DevOps request cannot be empty.")

        prompt = f"""
Analyze this DevOps request:

{request}

Return ONLY valid JSON using this structure:

{{
    "category": "AWS | KUBERNETES | CICD | TERRAFORM | MONITORING | SECURITY | GENERAL",
    "summary": "Brief description of the issue",
    "investigation_plan": [
        "Investigation step 1",
        "Investigation step 2",
        "Investigation step 3"
    ],
    "required_tools": [
        "List the tools that would be needed"
    ],
    "risk_level": "LOW | MEDIUM | HIGH"
}}
"""

        result = self.gemini.generate_response(
            system_prompt=DEVOPS_AGENT_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=1500,
            temperature=0.1,
        )

        try:
            plan = json.loads(result["answer"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(
                "The DevOps planner returned invalid JSON."
            ) from exc

        if not isinstance(plan, dict):
            raise ValueError("Planner response must be a JSON object.")

        allowed_categories = {
            "AWS", "KUBERNETES", "CICD",
            "TERRAFORM", "MONITORING",
            "SECURITY", "GENERAL",
        }

        allowed_risk_levels = {"LOW", "MEDIUM", "HIGH"}

        if plan.get("category") not in allowed_categories:
            raise ValueError("Invalid DevOps request category.")

        if not isinstance(plan.get("summary"), str) or not plan["summary"].strip():
            raise ValueError("Invalid plan summary.")

        if not isinstance(plan.get("investigation_plan"), list):
            raise ValueError("Invalid investigation plan.")

        if not all(
            isinstance(step, str) and step.strip()
            for step in plan["investigation_plan"]
        ):
            raise ValueError("Invalid investigation steps.")

        if not isinstance(plan.get("required_tools"), list):
            raise ValueError("Invalid required tools.")

        if not all(
            isinstance(tool, str) and tool.strip()
            for tool in plan["required_tools"]
        ):
            raise ValueError("Invalid required tools.")

        if plan.get("risk_level") not in allowed_risk_levels:
            raise ValueError("Invalid risk level.")

        return plan
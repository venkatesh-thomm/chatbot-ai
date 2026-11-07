from typing import TypedDict, Any


class DevOpsAgentState(TypedDict, total=False):
    request: str
    category: str
    investigation_plan: list[str]
    required_tools: list[str]
    risk_level: str
    findings: list[dict[str, Any]]
    response: str
    status: str

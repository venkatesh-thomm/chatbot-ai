from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    prompt: str
    environment: str = "prod"
    region: str | None = None
    intent: str = ""
    summary: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    output: dict = field(default_factory=dict)
    error: str | None = None
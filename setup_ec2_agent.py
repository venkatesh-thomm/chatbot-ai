
from pathlib import Path
import json

root = Path(__file__).resolve().parent

files = {
    "app/tools/__init__.py": "",

    "app/agents/state.py": '''
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
''',

    "app/tools/aws_ec2_tool.py": '''
import re
import boto3

from app.config import get_settings


class AWSEC2ReadOnlyTool:

    def __init__(self, client=None):
        settings = get_settings()
        self.region = settings.aws_region

        self.client = client or boto3.client(
            "ec2",
            region_name=self.region,
        )

    def inspect_instances(self, request: str) -> dict:

        match = re.search(
            r"\\bi-[0-9a-fA-F]{8,17}\\b",
            request,
        )

        instance_id = match.group(0) if match else None

        params = {}

        if instance_id:
            params["InstanceIds"] = [instance_id]
        else:
            params["Filters"] = [
                {
                    "Name": "instance-state-name",
                    "Values": [
                        "pending",
                        "running",
                        "stopping",
                        "stopped",
                    ],
                }
            ]

        paginator = self.client.get_paginator(
            "describe_instances"
        )

        instance_records = []

        pages = paginator.paginate(
            **params,
            PaginationConfig={
                "MaxItems": 100,
                "PageSize": 100,
            },
        )

        for page in pages:
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):

                    tags = {
                        tag["Key"]: tag["Value"]
                        for tag in instance.get("Tags", [])
                    }

                    launch_time = instance.get("LaunchTime")

                    instance_records.append({
                        "instance_id": instance.get("InstanceId"),
                        "name": tags.get("Name"),
                        "instance_type": instance.get("InstanceType"),
                        "state": instance.get("State", {}).get("Name"),
                        "availability_zone": instance.get(
                            "Placement", {}
                        ).get("AvailabilityZone"),
                        "vpc_id": instance.get("VpcId"),
                        "subnet_id": instance.get("SubnetId"),
                        "private_ip": instance.get("PrivateIpAddress"),
                        "security_groups": [
                            group.get("GroupId")
                            for group in instance.get("SecurityGroups", [])
                        ],
                        "launch_time": (
                            launch_time.isoformat()
                            if launch_time else None
                        ),
                    })

        instance_ids = [
            item["instance_id"]
            for item in instance_records
        ]

        status_map = {}

        if instance_ids:
            status_paginator = self.client.get_paginator(
                "describe_instance_status"
            )

            status_pages = status_paginator.paginate(
                InstanceIds=instance_ids,
                IncludeAllInstances=True,
                PaginationConfig={
                    "MaxItems": 100,
                    "PageSize": 100,
                },
            )

            for page in status_pages:
                for status in page.get("InstanceStatuses", []):

                    status_map[status["InstanceId"]] = {
                        "instance_status": status.get(
                            "InstanceStatus", {}
                        ).get("Status", "not_reported"),

                        "system_status": status.get(
                            "SystemStatus", {}
                        ).get("Status", "not_reported"),

                        "availability_zone": status.get(
                            "AvailabilityZone"
                        ),

                        "events": [
                            {
                                "code": event.get("Code"),
                                "description": event.get("Description"),
                            }
                            for event in status.get("Events", [])
                        ],
                    }

        for instance in instance_records:
            instance["status_checks"] = status_map.get(
                instance["instance_id"],
                {
                    "instance_status": "not_reported",
                    "system_status": "not_reported",
                    "events": [],
                },
            )

        return {
            "tool": "aws_ec2_read_only",
            "region": self.region,
            "instance_count": len(instance_records),
            "instances": instance_records,
            "scope": (
                f"Instance {instance_id}"
                if instance_id else "Non-terminated EC2 instances"
            ),
        }
''',

    "app/agents/graph.py": '''
import re

from langgraph.graph import StateGraph, START, END

from app.agents.state import DevOpsAgentState
from app.agents.planner import DevOpsPlanner
from app.tools.aws_ec2_tool import AWSEC2ReadOnlyTool


class DevOpsAgent:

    def __init__(self, planner=None, ec2_tool=None):

        self.planner = planner or DevOpsPlanner()
        self.ec2_tool = ec2_tool or AWSEC2ReadOnlyTool()

        workflow = StateGraph(DevOpsAgentState)

        workflow.add_node("planner", self.planner_node)
        workflow.add_node(
            "ec2_investigator",
            self.ec2_investigator_node,
        )

        workflow.add_edge(START, "planner")

        workflow.add_conditional_edges(
            "planner",
            self.route_after_planner,
            {
                "ec2": "ec2_investigator",
                "end": END,
            },
        )

        workflow.add_edge("ec2_investigator", END)

        self.graph = workflow.compile()

    def planner_node(self, state: DevOpsAgentState) -> dict:

        plan = self.planner.create_plan(state["request"])

        return {
            "category": plan["category"],
            "investigation_plan": plan["investigation_plan"],
            "required_tools": plan["required_tools"],
            "risk_level": plan["risk_level"],
            "response": plan["summary"],
            "status": "plan_created",
            "findings": [],
        }

    def route_after_planner(self, state: DevOpsAgentState) -> str:

        request = state.get("request", "")

        if re.search(
            r"\\b(ec2|instances?|virtual machine)\\b",
            request,
            re.IGNORECASE,
        ):
            return "ec2"

        return "end"

    def ec2_investigator_node(
        self,
        state: DevOpsAgentState,
    ) -> dict:

        findings = self.ec2_tool.inspect_instances(
            state["request"]
        )

        return {
            "findings": [findings],
            "status": "investigation_completed",
        }

    def run(self, request: str) -> dict:

        if not request or not request.strip():
            raise ValueError("Request cannot be empty.")

        initial_state = {
            "request": request,
            "status": "started",
            "findings": [],
        }

        return self.graph.invoke(initial_state)
''',

    "app/api/agent.py": '''
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.graph import DevOpsAgent


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/agent",
    tags=["DevOps Agent"],
)

agent = DevOpsAgent()


class AgentRequest(BaseModel):
    request: str = Field(..., min_length=1)


@router.post("/investigate")
def investigate(request: AgentRequest):

    try:
        result = agent.run(request.request)

        return {
            "status": result.get("status"),
            "category": result.get("category"),
            "summary": result.get("response"),
            "investigation_plan": result.get(
                "investigation_plan"
            ),
            "required_tools": result.get("required_tools"),
            "risk_level": result.get("risk_level"),
            "findings": result.get("findings", []),
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        logger.exception("DevOps agent investigation failed")

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )
'''
}

# Generate the minimum EC2 read-only IAM policy.
policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeInstances",
                "ec2:DescribeInstanceStatus"
            ],
            "Resource": "*"
        }
    ]
}

files[
    "infrastructure/iam/devops-agent-ec2-readonly-policy.json"
] = json.dumps(policy, indent=2)

# Write all generated files.
for relative_path, content in files.items():
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"Updated: {relative_path}")

# Verify existing AWS credentials and EC2 read access.
try:
    import boto3
    from app.config import get_settings

    settings = get_settings()

    sts = boto3.client(
        "sts",
        region_name=settings.aws_region,
    )

    identity = sts.get_caller_identity()

    ec2 = boto3.client(
        "ec2",
        region_name=settings.aws_region,
    )

    ec2.describe_instances(MaxResults=5)

    print("\\nAWS EC2 connectivity: SUCCESS")
    print("AWS account:", identity["Account"])
    print("AWS region:", settings.aws_region)

except Exception as exc:
    print("\\nAWS EC2 connectivity: FAILED")
    print(type(exc).__name__, str(exc))

print("\\nEC2 agent code generation completed.")

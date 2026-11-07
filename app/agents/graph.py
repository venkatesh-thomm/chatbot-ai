import re

from typing import TypedDict
from langgraph.graph import StateGraph, START, END

from app.agents.planner import DevOpsPlanner
from app.tools.aws_ec2_tool import AWSEC2ReadOnlyTool
from app.tools.aws_alb_tool import AWSALBReadOnlyTool
from app.tools.aws_cloudwatch_tool import AWSCloudWatchReadOnlyTool


class AgentState(TypedDict, total=False):
    request: str
    category: str
    investigation_plan: list
    required_tools: list
    risk_level: str
    findings: list
    response: str
    status: str


class DevOpsAgent:

    def __init__(self, planner=None):
        self.planner = planner or DevOpsPlanner()
        self.ec2_tool = AWSEC2ReadOnlyTool()
        self.alb_tool = AWSALBReadOnlyTool()
        self.cloudwatch_tool = AWSCloudWatchReadOnlyTool()

        workflow = StateGraph(AgentState)

        workflow.add_node("planner", self.planner_node)
        workflow.add_node("alb_investigator", self.alb_investigator)
        workflow.add_node("ec2_investigator", self.ec2_investigator)

        workflow.add_edge(START, "planner")

        workflow.add_conditional_edges(
            "planner",
            self.route_after_planner,
            {
                "alb": "alb_investigator",
                "ec2": "ec2_investigator",
                "end": END,
            },
        )

        workflow.add_conditional_edges(
            "alb_investigator",
            self.route_after_alb,
            {
                "ec2": "ec2_investigator",
                "end": END,
            },
        )

        workflow.add_edge("ec2_investigator", END)

        self.graph = workflow.compile()

    def planner_node(self, state: AgentState) -> dict:
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

    def route_after_planner(self, state: AgentState) -> str:
        request = state["request"].lower()

        if re.search(r"\b502\b|\b503\b|\bbad gateway\b", request):
            return "alb"

        if re.search(
            r"\balb\b|load balancer|target group|listener",
            request,
        ):
            return "alb"

        if re.search(
            r"\bec2\b|instances?|virtual machine",
            request,
        ):
            return "ec2"

        return "end"

    def route_after_alb(self, state: AgentState) -> str:
        request = state["request"].lower()

        if re.search(
            r"\b502\b|\b503\b|\bbad gateway\b|\bec2\b|instances?",
            request,
        ):
            return "ec2"

        return "end"

    def alb_investigator(self, state: AgentState) -> dict:
        alb_findings = self.alb_tool.inspect_load_balancers(
            state["request"]
        )

        cloudwatch_findings = []

        for lb in alb_findings.get("load_balancers", []):
            lb_arn = lb.get("LoadBalancerArn")

            if not lb_arn:
                continue

            groups = [
                group
                for group in alb_findings.get("target_groups", [])
                if group.get("load_balancer_name") == lb.get("LoadBalancerName")
            ]

            if not groups:
                cloudwatch_findings.append({
                    "load_balancer": lb.get("LoadBalancerName"),
                    "metrics": self.cloudwatch_tool.inspect_alb_metrics(
                        lb_arn
                    ),
                })
                continue

            for group in groups:
                cloudwatch_findings.append({
                    "load_balancer": lb.get("LoadBalancerName"),
                    "target_group": group.get("target_group_name"),
                    "metrics": self.cloudwatch_tool.inspect_alb_metrics(
                        lb_arn,
                        group.get("TargetGroupArn"),
                    ),
                })

        return {
            "findings": state.get("findings", []) + [
                {
                    "alb": alb_findings,
                    "cloudwatch_alb_metrics": cloudwatch_findings,
                }
            ],
            "status": "alb_investigation_completed",
        }

    def ec2_investigator(self, state: AgentState) -> dict:
        ec2_findings = self.ec2_tool.inspect_instances(
            state["request"]
        )

        cloudwatch_findings = []

        for instance in ec2_findings.get("instances", []):
            instance_id = instance.get("instance_id")

            if instance_id:
                cloudwatch_findings.append({
                    "instance_id": instance_id,
                    "metrics": self.cloudwatch_tool.inspect_ec2_metrics(
                        instance_id
                    ),
                })

        return {
            "findings": state.get("findings", []) + [
                {
                    "ec2": ec2_findings,
                    "cloudwatch_ec2_metrics": cloudwatch_findings,
                }
            ],
            "status": "investigation_completed",
        }

    def run(self, request: str) -> dict:
        return self.graph.invoke({
            "request": request,
            "status": "started",
            "findings": [],
        })
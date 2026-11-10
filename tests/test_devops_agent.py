import json
from types import SimpleNamespace

import pytest

from app.agents.graph import DevOpsAgent
from app.agents.analyzer import DevOpsAnalyzer
from app.agents.planner import DevOpsPlanner
from app.config import Settings
from app.tools.kubernetes_tool import KubernetesTool


class FakeGeminiService:
    def __init__(self, answer: str):
        self.answer = answer

    def generate_response(self, **kwargs):
        return {"answer": self.answer}


def valid_plan():
    return {
        "category": "AWS",
        "summary": "Investigate elevated CPU.",
        "investigation_plan": ["Review CPU metrics."],
        "required_tools": ["CloudWatch"],
        "risk_level": "LOW",
    }


def test_planner_validates_model_plan():
    planner = DevOpsPlanner(
        gemini_service=FakeGeminiService(json.dumps(valid_plan()))
    )

    assert planner.create_plan("Investigate CPU") == valid_plan()


def test_planner_rejects_invalid_category():
    plan = valid_plan()
    plan["category"] = "EXECUTE_COMMANDS"
    planner = DevOpsPlanner(
        gemini_service=FakeGeminiService(json.dumps(plan))
    )

    with pytest.raises(ValueError, match="category"):
        planner.create_plan("Investigate CPU")


def test_agent_returns_plan_without_executing_tools():
    plan = valid_plan()

    class FakePlanner:
        def create_plan(self, request):
            return plan

    result = DevOpsAgent(region="us-east-1", planner=FakePlanner()).run(
        "Investigate CPU",
        environment="development",
    )

    assert result["status"] == "planned"
    assert result["tool_calls"] == []
    assert result["output"]["execution_mode"] == "plan_only"


def test_agent_stops_only_running_instance_with_configured_tag():
    class FakeEC2Tool:
        def __init__(self):
            self.stop_calls = []

        def get_instance(self, instance_id):
            return {
                "instance_id": instance_id,
                "state": "running",
                "tags": {"Environment": "development"},
            }

        def stop_instance(self, instance_id):
            self.stop_calls.append(instance_id)
            return {"status": "stopping", "instance_id": instance_id}

    ec2 = FakeEC2Tool()
    settings = Settings(
        aws_region="us-east-1",
        devops_allowed_environment="development",
        devops_allowed_ec2_actions="stop_instance",
        devops_target_tag_key="Environment",
        devops_target_tag_value="development",
    )
    agent = DevOpsAgent(
        settings=settings,
        ec2_tool=ec2,
    )

    result = agent.run(
        "Stop the development instance",
        environment="development",
        action="stop_instance",
        target_instance_id="i-0123456789abcdef0",
    )

    assert result["status"] == "completed"
    assert ec2.stop_calls == ["i-0123456789abcdef0"]


def test_agent_does_not_stop_instance_outside_configured_tag():
    class FakeEC2Tool:
        def get_instance(self, instance_id):
            return {
                "instance_id": instance_id,
                "state": "running",
                "tags": {"Environment": "production"},
            }

        def stop_instance(self, instance_id):
            pytest.fail("The agent must not stop an out-of-scope instance.")

    settings = Settings(
        aws_region="us-east-1",
        devops_allowed_environment="development",
        devops_allowed_ec2_actions="stop_instance",
        devops_target_tag_key="Environment",
        devops_target_tag_value="development",
    )
    agent = DevOpsAgent(settings=settings, ec2_tool=FakeEC2Tool())

    with pytest.raises(PermissionError, match="target tag"):
        agent.run(
            "Stop this instance",
            environment="development",
            action="stop_instance",
            target_instance_id="i-0123456789abcdef0",
        )


def test_agent_blocks_mutation_without_explicit_action_allowlist():
    class FakeEC2Tool:
        def get_instance(self, instance_id):
            pytest.fail("The target should not be queried when mutation is disabled.")

    settings = Settings(
        aws_region="us-east-1",
        devops_allowed_environment="development",
        devops_target_tag_key="Environment",
        devops_target_tag_value="development",
    )
    agent = DevOpsAgent(settings=settings, ec2_tool=FakeEC2Tool())

    with pytest.raises(PermissionError, match="disabled"):
        agent.run(
            "Stop this instance",
            environment="development",
            action="stop_instance",
            target_instance_id="i-0123456789abcdef0",
        )


def test_agent_lists_only_configured_environment_tag():
    class FakeEC2Tool:
        def __init__(self):
            self.scope = None

        def list_instances(self, **kwargs):
            self.scope = kwargs
            return {"instances": []}

    ec2 = FakeEC2Tool()
    settings = Settings(
        aws_region="us-east-1",
        devops_allowed_environment="development",
        devops_target_tag_key="Environment",
        devops_target_tag_value="development",
    )
    agent = DevOpsAgent(settings=settings, ec2_tool=ec2)

    agent.run(
        "List instances",
        environment="development",
        action="list_instances",
    )

    assert ec2.scope == {
        "tag_key": "Environment",
        "tag_value": "development",
    }


def test_agent_lists_pods_only_in_configured_namespace():
    class FakeKubernetesTool:
        def __init__(self):
            self.called = False

        def list_pods(self):
            self.called = True
            return {
                "namespace": "default",
                "pods": [{"name": "api-123", "ready": True}],
                "pod_count": 1,
                "unhealthy_pod_count": 0,
            }

    k8s = FakeKubernetesTool()
    settings = Settings(
        aws_region="us-east-1",
        devops_allowed_environment="development",
        devops_kubernetes_namespace="default",
    )
    agent = DevOpsAgent(settings=settings, kubernetes_tool=k8s)

    result = agent.run(
        "Check Kubernetes pod health",
        environment="development",
        action="list_pods",
    )

    assert k8s.called
    assert result["status"] == "completed"
    assert result["output"]["namespace"] == "default"
    assert result["output"]["unhealthy_pod_count"] == 0


def test_kubernetes_pod_summary_includes_readiness_and_restarts():
    pod = SimpleNamespace(
        metadata=SimpleNamespace(name="api-123", namespace="default"),
        spec=SimpleNamespace(node_name="node-1"),
        status=SimpleNamespace(
            phase="Running",
            pod_ip="10.0.0.8",
            container_statuses=[
                SimpleNamespace(
                    name="api",
                    ready=False,
                    restart_count=3,
                    state=SimpleNamespace(
                        waiting=SimpleNamespace(reason="CrashLoopBackOff"),
                        terminated=None,
                        running=None,
                    ),
                )
            ],
        ),
    )

    summary = KubernetesTool._pod_summary(pod)

    assert summary["phase"] == "Running"
    assert summary["ready"] is False
    assert summary["restart_count"] == 3
    assert summary["containers"][0]["reason"] == "CrashLoopBackOff"


def test_health_analyzer_reports_ec2_and_pod_signals_with_possible_causes():
    diagnosis = DevOpsAnalyzer().analyze_runtime_health(
        instances=[
            {
                "instance_id": "i-0123456789abcdef0",
                "state": "stopped",
                "state_reason": "User initiated",
                "status_checks": None,
            }
        ],
        pods=[
            {
                "name": "api-123",
                "namespace": "default",
                "phase": "Running",
                "ready": False,
                "restart_count": 4,
                "containers": [
                    {
                        "name": "api",
                        "reason": "CrashLoopBackOff",
                    }
                ],
                "warning_events": [
                    {
                        "reason": "BackOff",
                        "message": "Back-off restarting failed container",
                    }
                ],
            }
        ],
    )

    assert diagnosis["status"] == "issues_detected"
    assert any("stopped" in item for item in diagnosis["observations"])
    assert any("CrashLoopBackOff" in item for item in diagnosis["observations"])
    assert any("Back-off" in item for item in diagnosis["observations"])
    assert diagnosis["possible_causes"]


def test_health_analyzer_does_not_flag_successful_job_pod():
    diagnosis = DevOpsAnalyzer().analyze_runtime_health(
        pods=[
            {
                "name": "job-123",
                "namespace": "default",
                "phase": "Succeeded",
                "ready": False,
                "restart_count": 0,
                "containers": [],
                "warning_events": [],
            }
        ]
    )

    assert diagnosis["status"] == "healthy"
    assert diagnosis["observations"] == []


def test_health_analyzer_does_not_claim_healthy_without_ec2_status_checks():
    diagnosis = DevOpsAnalyzer().analyze_runtime_health(
        instances=[
            {
                "instance_id": "i-0123456789abcdef0",
                "state": "running",
                "status_checks": None,
            }
        ]
    )

    assert diagnosis["status"] == "insufficient_evidence"
    assert diagnosis["evidence_gaps"]


def test_combined_health_check_reports_ec2_and_kubernetes_findings():
    class FakeEC2Tool:
        def list_instances(self, **kwargs):
            return {
                "instances": [
                    {
                        "instance_id": "i-0123456789abcdef0",
                        "state": "stopped",
                        "state_reason": "User initiated",
                    }
                ]
            }

    class FakeKubernetesTool:
        def list_pods(self):
            return {
                "namespace": "default",
                "pods": [
                    {
                        "name": "api-123",
                        "namespace": "default",
                        "phase": "Pending",
                        "ready": False,
                        "restart_count": 0,
                        "containers": [],
                        "warning_events": [],
                    }
                ],
                "pod_count": 1,
                "unhealthy_pod_count": 1,
            }

    settings = Settings(
        aws_region="us-east-1",
        devops_allowed_environment="development",
        devops_target_tag_key="Environment",
        devops_target_tag_value="development",
        devops_kubernetes_namespace="default",
    )
    result = DevOpsAgent(
        settings=settings,
        ec2_tool=FakeEC2Tool(),
        kubernetes_tool=FakeKubernetesTool(),
    ).run(
        "Check whether EC2 instances or Kubernetes pods are down",
        environment="development",
        action="check_health",
    )

    assert result["output"]["diagnosis"]["status"] == "issues_detected"
    assert result["output"]["ec2"]["instances"][0]["state"] == "stopped"
    assert result["output"]["kubernetes"]["pods"][0]["phase"] == "Pending"

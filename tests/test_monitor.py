import pytest

from app.config import Settings
from app.monitoring.monitor import MonitorConfigurationError, run_monitor


class FakeStateTable:
    def __init__(self):
        self.item = None

    def get_item(self, *, Key):
        return {"Item": self.item} if self.item else {}

    def put_item(self, *, Item):
        self.item = Item


class FakeSNS:
    def __init__(self):
        self.messages = []

    def publish(self, **kwargs):
        self.messages.append(kwargs)


class FakeEC2Tool:
    def __init__(self):
        self.instances = []

    def list_instances(self, **kwargs):
        assert kwargs == {"tag_key": "Environment", "tag_value": "development"}
        return {"instances": self.instances}


class FakeKubernetesTool:
    def __init__(self):
        self.pods = []

    def list_pods(self):
        return {"pods": self.pods}


def monitor_settings(**overrides):
    values = {
        "environment": "development",
        "aws_region": "us-east-1",
        "devops_kubernetes_namespace": "default",
        "devops_target_tag_key": "Environment",
        "devops_target_tag_value": "development",
        "devops_alerts_sns_topic_arn": "arn:aws:sns:us-east-1:123456789012:alerts",
        "devops_monitor_state_table": "devops-monitor-state",
    }
    values.update(overrides)
    return Settings(**values)


def test_monitor_deduplicates_incident_alerts_and_sends_recovery():
    ec2 = FakeEC2Tool()
    kubernetes = FakeKubernetesTool()
    sns = FakeSNS()
    state = FakeStateTable()

    ec2.instances = [
        {
            "instance_id": "i-0123456789abcdef0",
            "state": "running",
            "status_checks": {
                "instance_status": "ok",
                "system_status": "ok",
                "events": [],
            },
        }
    ]
    kubernetes.pods = [
        {
            "name": "api-123",
            "namespace": "default",
            "phase": "Pending",
            "ready": False,
            "restart_count": 0,
            "containers": [],
            "warning_events": [],
        }
    ]

    dependencies = {
        "settings": monitor_settings(),
        "ec2_tool": ec2,
        "kubernetes_tool": kubernetes,
        "sns_client": sns,
        "state_table": state,
    }

    first = run_monitor(**dependencies)
    repeated = run_monitor(**dependencies)

    assert first["diagnosis"]["status"] == "issues_detected"
    assert first["alert_sent"] is True
    assert repeated["alert_sent"] is False
    assert len(sns.messages) == 1

    kubernetes.pods[0]["phase"] = "Running"
    kubernetes.pods[0]["ready"] = True
    recovered = run_monitor(**dependencies)

    assert recovered["diagnosis"]["status"] == "healthy"
    assert recovered["alert_sent"] is True
    assert len(sns.messages) == 2
    assert "healthy" in sns.messages[-1]["Subject"]


def test_monitor_fails_fast_on_unreplaced_deployment_values():
    settings = monitor_settings(
        devops_target_tag_key="REPLACE_WITH_INSTANCE_TAG_KEY"
    )

    with pytest.raises(MonitorConfigurationError, match="placeholder"):
        run_monitor(settings=settings)

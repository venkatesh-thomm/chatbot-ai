import json
import logging
from typing import Any

import boto3

from app.agents.analyzer import DevOpsAnalyzer
from app.config import Settings, get_settings
from app.tools.aws_ec2_tool import EC2Tool
from app.tools.kubernetes_tool import KubernetesTool

logger = logging.getLogger(__name__)


class MonitorConfigurationError(RuntimeError):
    """Raised when required monitoring resources are not configured."""


def run_monitor(
    *,
    settings: Settings | None = None,
    ec2_tool=None,
    kubernetes_tool=None,
    analyzer=None,
    sns_client=None,
    state_table=None,
) -> dict[str, Any]:
    """Run one read-only health check and publish only state transitions."""
    settings = settings or get_settings()

    required_settings = {
        "DEVOPS_TARGET_TAG_KEY": settings.devops_target_tag_key,
        "DEVOPS_TARGET_TAG_VALUE": settings.devops_target_tag_value,
        "DEVOPS_ALERTS_SNS_TOPIC_ARN": settings.devops_alerts_sns_topic_arn,
        "DEVOPS_MONITOR_STATE_TABLE": settings.devops_monitor_state_table,
    }
    missing = [key for key, value in required_settings.items() if not value]
    missing.extend(
        key
        for key, value in required_settings.items()
        if isinstance(value, str) and value.startswith("REPLACE_WITH_")
    )
    if missing:
        raise MonitorConfigurationError(
            "Missing or placeholder monitor settings: "
            + ", ".join(dict.fromkeys(missing))
        )

    ec2_tool = ec2_tool or EC2Tool(region=settings.aws_region)
    kubernetes_tool = kubernetes_tool or KubernetesTool(
        namespace=settings.devops_kubernetes_namespace
    )
    analyzer = analyzer or DevOpsAnalyzer()
    sns_client = sns_client or boto3.client("sns", region_name=settings.aws_region)
    state_table = state_table or boto3.resource(
        "dynamodb", region_name=settings.aws_region
    ).Table(settings.devops_monitor_state_table)

    instances_result = ec2_tool.list_instances(
        tag_key=settings.devops_target_tag_key,
        tag_value=settings.devops_target_tag_value,
    )
    pods_result = kubernetes_tool.list_pods()
    diagnosis = analyzer.analyze_runtime_health(
        instances=instances_result["instances"],
        pods=pods_result["pods"],
    )
    if not instances_result["instances"]:
        diagnosis["evidence_gaps"].append(
            "No EC2 instances matched the configured target tag."
        )
    if not pods_result["pods"]:
        diagnosis["evidence_gaps"].append(
            f"No pods were found in namespace {settings.devops_kubernetes_namespace}."
        )
    if diagnosis["status"] == "healthy" and diagnosis["evidence_gaps"]:
        diagnosis["status"] = "insufficient_evidence"
        diagnosis["conclusion"] = (
            "No unhealthy signal was confirmed, but one or more monitored "
            "resource groups returned no health evidence."
        )

    monitor_id = (
        f"{settings.environment}:{settings.aws_region}:"
        f"{settings.devops_kubernetes_namespace}"
    )
    previous_item = state_table.get_item(Key={"monitor_id": monitor_id}).get(
        "Item", {}
    )
    previous_status = previous_item.get("status")

    # Alert on status transitions rather than every five-minute CronJob run.
    is_healthy = diagnosis["status"] == "healthy"
    alert_needed = (
        (
            not is_healthy
            and previous_status != diagnosis["status"]
        )
        or (is_healthy and previous_status not in {None, "healthy"})
    )
    alert_sent = False

    if alert_needed:
        subject = (
            f"DevOps monitor: {diagnosis['status']} "
            f"({settings.environment}/{settings.aws_region})"
        )[:100]
        message = {
            "environment": settings.environment,
            "region": settings.aws_region,
            "namespace": settings.devops_kubernetes_namespace,
            "status": diagnosis["status"],
            "conclusion": diagnosis["conclusion"],
            "observations": diagnosis["observations"],
            "possible_causes": diagnosis["possible_causes"],
            "evidence_gaps": diagnosis["evidence_gaps"],
        }
        sns_client.publish(
            TopicArn=settings.devops_alerts_sns_topic_arn,
            Subject=subject,
            Message=json.dumps(message, indent=2, default=str),
        )
        alert_sent = True

    state_table.put_item(
        Item={
            "monitor_id": monitor_id,
            "status": diagnosis["status"],
        }
    )

    logger.info(
        "Health check complete: status=%s resources=%s alert_sent=%s",
        diagnosis["status"],
        diagnosis["checked_resource_count"],
        alert_sent,
    )
    return {
        "diagnosis": diagnosis,
        "alert_sent": alert_sent,
        "monitor_id": monitor_id,
    }

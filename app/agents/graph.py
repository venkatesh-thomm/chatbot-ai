import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.agents.planner import DevOpsPlanner
from app.agents.analyzer import DevOpsAnalyzer
from app.config import Settings, get_settings
from app.tools.aws_alb_tool import ALBTool
from app.tools.aws_cloudwatch_tool import CloudWatchTool
from app.tools.aws_ec2_tool import EC2Tool
from app.tools.kubernetes_tool import KubernetesTool


logger = logging.getLogger(__name__)


class AgentPolicyError(PermissionError):
    """Raised when a requested agent action falls outside configured policy."""


class DevOpsAgent:

    def __init__(
        self,
        region: str | None = None,
        planner=None,
        ec2_tool=None,
        cloudwatch_tool=None,
        kubernetes_tool=None,
        settings: Settings | None = None,
        alb_tool=None,
    ):
        self.settings = settings or get_settings()
        self.region = region or self.settings.aws_region

        self.planner = planner
        self.ec2_tool = ec2_tool
        self.cloudwatch_tool = cloudwatch_tool
        self.kubernetes_tool = kubernetes_tool
        self.alb_tool = alb_tool

        self.analyzer = DevOpsAnalyzer()

    def _ec2(self) -> EC2Tool:
        if self.ec2_tool is None:
            self.ec2_tool = EC2Tool(region=self.region)

        return self.ec2_tool

    def _cloudwatch(self) -> CloudWatchTool:
        if self.cloudwatch_tool is None:
            self.cloudwatch_tool = CloudWatchTool(
                region=self.region
            )

        return self.cloudwatch_tool

    def _kubernetes(self) -> KubernetesTool:
        if self.kubernetes_tool is None:
            self.kubernetes_tool = KubernetesTool(
                namespace=self.settings.devops_kubernetes_namespace
            )

        return self.kubernetes_tool

    def _alb(self) -> ALBTool:
        if self.alb_tool is None:
            self.alb_tool = ALBTool(
                region=self.region
            )

        return self.alb_tool

    def _validate_scope(
        self,
        environment: str,
        request_region: str | None,
    ) -> None:
        if environment != self.settings.devops_allowed_environment:
            raise AgentPolicyError(
                "The requested environment is outside the configured agent scope."
            )

        if request_region and request_region != self.settings.aws_region:
            raise AgentPolicyError(
                "The requested AWS region is outside the configured agent scope."
            )

    def _plan(self, prompt: str, environment: str) -> dict:
        if self.planner is None:
            self.planner = DevOpsPlanner()

        plan = self.planner.create_plan(
            f"Environment: {environment}\n"
            f"AWS region: {self.region}\n"
            f"Request: {prompt}"
        )

        return {
            "status": "planned",
            "intent": plan["category"],
            "summary": plan["summary"],
            "tool_calls": [],
            "output": {
                "investigation_plan": plan["investigation_plan"],
                "required_tools": plan["required_tools"],
                "risk_level": plan["risk_level"],
                "execution_mode": "plan_only",
            },
        }

    def _collect_ec2_health(self) -> dict:
        try:
            tag_key, tag_value = self._target_tag()

            result = self._ec2().list_instances(
                tag_key=tag_key,
                tag_value=tag_value,
            )

            return {
                "status": "completed",
                **result,
            }

        except Exception as exc:
            logger.exception("EC2 health investigation failed")

            return {
                "status": "failed",
                "error": (
                    f"EC2 investigation failed ({type(exc).__name__}). "
                    "Check application logs."
                ),
                "instances": [],
            }

    def _collect_kubernetes_health(self) -> dict:
        try:
            result = self._kubernetes().list_pods()

            return {
                "status": "completed",
                **result,
            }

        except Exception as exc:
            logger.exception("Kubernetes health investigation failed")

            return {
                "status": "failed",
                "error": (
                    f"Kubernetes investigation failed "
                    f"({type(exc).__name__}). Check application logs."
                ),
                "pods": [],
            }

    def _collect_alb_health(self) -> dict:
        try:
            result = self._alb().inspect_load_balancers()

            return {
                "status": "completed",
                **result,
            }

        except Exception as exc:
            logger.exception("ALB health investigation failed")

            return {
                "status": "failed",
                "error": (
                    f"ALB investigation failed ({type(exc).__name__}). "
                    "Check application logs and ELB permissions."
                ),
                "load_balancer_count": 0,
                "load_balancers": [],
            }

    def _collect_cloudwatch_instance(
        self,
        cloudwatch: CloudWatchTool,
        instance_id: str,
    ) -> dict:
        try:
            result = cloudwatch.get_instance_health_metrics(
                instance_id
            )

            return {
                "instance_id": instance_id,
                "status": "completed",
                "metrics": result.get("metrics", {}),
            }

        except Exception as exc:
            logger.exception(
                "CloudWatch investigation failed for %s",
                instance_id,
            )

            return {
                "instance_id": instance_id,
                "status": "failed",
                "error": type(exc).__name__,
                "metrics": {},
            }

    def _collect_cloudwatch_health(
        self,
        instances: list[dict],
    ) -> dict:
        instance_ids = [
            instance["instance_id"]
            for instance in instances
            if instance.get("instance_id")
        ]

        if not instance_ids:
            return {
                "status": "skipped",
                "reason": "No scoped EC2 instances were found.",
                "instance_metrics": [],
            }

        try:
            cloudwatch = self._cloudwatch()
        except Exception as exc:
            logger.exception("CloudWatch client initialization failed")

            return {
                "status": "failed",
                "reason": f"CloudWatch initialization failed ({type(exc).__name__}).",
                "instance_metrics": [
                    {
                        "instance_id": instance_id,
                        "status": "failed",
                        "error": type(exc).__name__,
                        "metrics": {},
                    }
                    for instance_id in instance_ids
                ],
            }

        results = []

        with ThreadPoolExecutor(
            max_workers=min(4, len(instance_ids)),
            thread_name_prefix="cloudwatch",
        ) as executor:

            futures = {
                executor.submit(
                    self._collect_cloudwatch_instance,
                    cloudwatch,
                    instance_id,
                ): instance_id
                for instance_id in instance_ids
            }

            for future in as_completed(futures):
                results.append(future.result())

        results.sort(
            key=lambda item: item["instance_id"]
        )

        failed_count = sum(
            item["status"] == "failed"
            for item in results
        )

        if failed_count == 0:
            status = "completed"
        elif failed_count == len(results):
            status = "failed"
        else:
            status = "partial"

        return {
            "status": status,
            "instance_metrics": results,
        }

    def _check_health_parallel(self) -> dict:
        # EC2, Kubernetes, and ALB investigations are independent.
        with ThreadPoolExecutor(
            max_workers=3,
            thread_name_prefix="devops-investigation",
        ) as executor:

            ec2_future = executor.submit(
                self._collect_ec2_health,
            )

            kubernetes_future = executor.submit(
                self._collect_kubernetes_health,
            )

            alb_future = executor.submit(
                self._collect_alb_health,
            )

            # Start CloudWatch after EC2 inventory is available.
            ec2_result = ec2_future.result()

            if ec2_result["status"] == "completed":
                cloudwatch_result = self._collect_cloudwatch_health(
                    ec2_result.get("instances", [])
                )
            else:
                cloudwatch_result = {
                    "status": "skipped",
                    "reason": "EC2 inventory was unavailable.",
                    "instance_metrics": [],
                }

            kubernetes_result = kubernetes_future.result()
            alb_result = alb_future.result()

        instances = ec2_result.get("instances", [])
        pods = kubernetes_result.get("pods", [])

        diagnosis = self.analyzer.analyze_runtime_health(
            instances=instances,
            pods=pods,
            cloudwatch_metrics=cloudwatch_result.get(
                "instance_metrics",
                [],
            ),
            alb_health=alb_result,
        )

        # Empty inventories are not proof that infrastructure is healthy.
        if (
            ec2_result["status"] == "completed"
            and not instances
        ):
            diagnosis["evidence_gaps"].append(
                "No EC2 instances matched the configured target tag."
            )

        if (
            kubernetes_result["status"] == "completed"
            and not pods
        ):
            diagnosis["evidence_gaps"].append(
                "No Kubernetes Pods were found in the configured namespace."
            )

        if cloudwatch_result["status"] in {"failed", "partial"}:
            diagnosis["evidence_gaps"].append(
                "Some CloudWatch metrics could not be collected."
            )

        diagnosis["evidence_gaps"] = list(
            dict.fromkeys(diagnosis["evidence_gaps"])
        )

        if (
            diagnosis["status"] == "healthy"
            and diagnosis["evidence_gaps"]
        ):
            diagnosis["status"] = "insufficient_evidence"
            diagnosis["conclusion"] = (
                "No unhealthy signal was confirmed, but some "
                "infrastructure evidence is incomplete."
            )

        investigation_statuses = [
            ec2_result["status"],
            kubernetes_result["status"],
            alb_result["status"],
        ]

        successful_investigations = sum(
            status == "completed"
            for status in investigation_statuses
        )

        if successful_investigations == 0:
            execution_status = "failed"

        elif (
            successful_investigations == len(investigation_statuses)
            and cloudwatch_result["status"] in {"completed", "skipped"}
        ):
            execution_status = "completed"

        else:
            execution_status = "partial"

        if execution_status == "partial":
            summary = (
                "Investigation partially completed. "
                + diagnosis["conclusion"]
            )

        elif execution_status == "failed":
            summary = (
                "Infrastructure investigation failed. "
                "Check the service logs for details."
            )

        else:
            summary = diagnosis["conclusion"]

        return {
            "status": execution_status,
            "intent": "check_health",
            "summary": summary,
            "tool_calls": [
                {
                    "tool": "ec2",
                    "action": "list_instances",
                    "status": ec2_result["status"],
                },
                {
                    "tool": "kubernetes",
                    "action": "list_pods",
                    "status": kubernetes_result["status"],
                },
                {
                    "tool": "cloudwatch",
                    "action": "get_instance_health_metrics",
                    "status": cloudwatch_result["status"],
                },
                {
                    "tool": "alb",
                    "action": "inspect_load_balancers",
                    "status": alb_result["status"],
                },
            ],
            "output": {
                "ec2": ec2_result,
                "kubernetes": kubernetes_result,
                "cloudwatch": cloudwatch_result,
                "alb": alb_result,
                "diagnosis": diagnosis,
            },
        }

    def run(
        self,
        prompt: str,
        environment: str = "development",
        action: str = "plan",
        target_instance_id: str | None = None,
        request_region: str | None = None,
    ) -> dict:

        self._validate_scope(environment, request_region)

        if action == "plan":
            return self._plan(prompt, environment)

        if action == "list_instances":
            tag_key, tag_value = self._target_tag()

            result = self._ec2().list_instances(
                tag_key=tag_key,
                tag_value=tag_value,
            )

            result["diagnosis"] = self.analyzer.analyze_runtime_health(
                instances=result["instances"],
            )

            return {
                "status": "completed",
                "intent": "ec2_health",
                "summary": result["diagnosis"]["conclusion"],
                "tool_calls": [
                    {
                        "tool": "ec2",
                        "action": action,
                        "args": {},
                    }
                ],
                "output": result,
            }

        if action == "get_instance_cpu":
            if not target_instance_id:
                raise ValueError(
                    "target_instance_id is required."
                )

            self._get_scoped_instance(target_instance_id)

            result = self._cloudwatch().get_instance_cpu(
                target_instance_id
            )

            return {
                "status": "completed",
                "intent": action,
                "summary": (
                    f"Retrieved CloudWatch CPU metrics for "
                    f"{target_instance_id}."
                ),
                "tool_calls": [
                    {
                        "tool": "cloudwatch",
                        "action": action,
                        "args": {
                            "instance_id": target_instance_id
                        },
                    }
                ],
                "output": result,
            }

        if action == "list_pods":
            result = self._kubernetes().list_pods()

            result["diagnosis"] = self.analyzer.analyze_runtime_health(
                pods=result["pods"],
            )

            return {
                "status": "completed",
                "intent": "kubernetes_health",
                "summary": result["diagnosis"]["conclusion"],
                "tool_calls": [
                    {
                        "tool": "kubernetes",
                        "action": action,
                        "args": {
                            "namespace": self.settings.devops_kubernetes_namespace
                        },
                    }
                ],
                "output": result,
            }

        if action == "check_health":
            return self._check_health_parallel()

        if action == "stop_instance":
            return self._stop_instance(target_instance_id)

        raise AgentPolicyError(
            "The requested action is not allowlisted."
        )

    def _stop_instance(
        self,
        instance_id: str | None,
    ) -> dict:

        if not instance_id:
            raise ValueError(
                "target_instance_id is required."
            )

        if "stop_instance" not in self.settings.allowed_ec2_actions:
            raise AgentPolicyError(
                "EC2 stop is disabled; add stop_instance to "
                "DEVOPS_ALLOWED_EC2_ACTIONS to enable it."
            )

        instance = self._get_scoped_instance(instance_id)

        if instance["state"] != "running":
            raise AgentPolicyError(
                "Only running EC2 instances can be stopped by this agent."
            )

        result = self._ec2().stop_instance(instance_id)

        return {
            "status": "completed",
            "intent": "stop_instance",
            "summary": (
                f"Submitted a stop request for EC2 instance {instance_id}."
            ),
            "tool_calls": [
                {
                    "tool": "ec2",
                    "action": "stop_instance",
                    "args": {
                        "instance_id": instance_id
                    },
                }
            ],
            "output": result,
        }

    def _target_tag(self) -> tuple[str, str]:
        tag_key = self.settings.devops_target_tag_key
        tag_value = self.settings.devops_target_tag_value

        if not tag_key or not tag_value:
            raise AgentPolicyError(
                "AWS resource access is disabled until the target "
                "tag key and value are configured."
            )

        return tag_key, tag_value

    def _get_scoped_instance(self, instance_id: str) -> dict:
        tag_key, tag_value = self._target_tag()

        instance = self._ec2().get_instance(instance_id)

        if instance is None:
            raise LookupError(
                "The requested EC2 instance was not found."
            )

        if instance["tags"].get(tag_key) != tag_value:
            raise AgentPolicyError(
                "The EC2 instance does not match the configured target tag."
            )

        return instance
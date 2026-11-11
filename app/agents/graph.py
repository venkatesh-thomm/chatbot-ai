
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

    @staticmethod
    def _aggregate_status(results: list[dict]) -> str:
        if not results:
            return "skipped"

        statuses = [
            item.get("status", "failed")
            for item in results
        ]

        if all(status == "completed" for status in statuses):
            return "completed"

        if all(status == "failed" for status in statuses):
            return "failed"

        return "partial"

    def _collect_cloudwatch_instance(
        self,
        cloudwatch: CloudWatchTool,
        instance_id: str,
    ) -> dict:
        try:
            result = cloudwatch.get_instance_health_metrics(
                instance_id
            )

            status = result.get("status", "failed")

            if status not in {"completed", "partial", "failed"}:
                status = "failed"

            return {
                "instance_id": instance_id,
                "status": status,
                "metrics": result.get("metrics", {}),
            }

        except Exception as exc:
            logger.exception(
                "CloudWatch EC2 metrics failed for %s",
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
                "reason": (
                    f"CloudWatch initialization failed "
                    f"({type(exc).__name__})."
                ),
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
            thread_name_prefix="cloudwatch-ec2",
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

        return {
            "status": self._aggregate_status(results),
            "instance_metrics": results,
        }

    def _collect_cloudwatch_alb_instance(
        self,
        cloudwatch: CloudWatchTool,
        load_balancer: dict,
    ) -> dict:
        load_balancer_arn = load_balancer["load_balancer_arn"]
        load_balancer_name = load_balancer.get("name", "unknown")

        try:
            result = cloudwatch.get_alb_metrics(
                load_balancer_arn=load_balancer_arn,
                target_groups=load_balancer.get("target_groups", []),
            )

            status = result.get("status", "failed")

            if status not in {"completed", "partial", "failed"}:
                status = "failed"

            return {
                "load_balancer_arn": load_balancer_arn,
                "load_balancer_name": load_balancer_name,
                "status": status,
                "load_balancer_metrics": result.get(
                    "load_balancer_metrics",
                    {},
                ),
                "target_group_metrics": result.get(
                    "target_group_metrics",
                    [],
                ),
            }

        except Exception as exc:
            logger.exception(
                "CloudWatch ALB metrics failed for %s",
                load_balancer_name,
            )

            return {
                "load_balancer_arn": load_balancer_arn,
                "load_balancer_name": load_balancer_name,
                "status": "failed",
                "error": type(exc).__name__,
                "load_balancer_metrics": {},
                "target_group_metrics": [],
            }

    def _collect_cloudwatch_alb_health(
        self,
        alb_result: dict,
    ) -> dict:
        if alb_result.get("status") != "completed":
            return {
                "status": "skipped",
                "reason": "ALB inventory was unavailable.",
                "load_balancers": [],
            }

        load_balancers = alb_result.get("load_balancers", [])

        if not load_balancers:
            return {
                "status": "skipped",
                "reason": "No Application Load Balancers were found.",
                "load_balancers": [],
            }

        try:
            cloudwatch = self._cloudwatch()

        except Exception as exc:
            logger.exception(
                "CloudWatch client initialization failed for ALB metrics"
            )

            return {
                "status": "failed",
                "reason": (
                    f"CloudWatch initialization failed "
                    f"({type(exc).__name__})."
                ),
                "load_balancers": [],
            }

        results = []

        with ThreadPoolExecutor(
            max_workers=min(4, len(load_balancers)),
            thread_name_prefix="cloudwatch-alb",
        ) as executor:

            futures = {
                executor.submit(
                    self._collect_cloudwatch_alb_instance,
                    cloudwatch,
                    load_balancer,
                ): load_balancer.get("name", "unknown")
                for load_balancer in load_balancers
            }

            for future in as_completed(futures):
                results.append(future.result())

        results.sort(
            key=lambda item: item["load_balancer_name"]
        )

        return {
            "status": self._aggregate_status(results),
            "load_balancers": results,
        }

    def _collect_cloudwatch_alarms(
        self,
        instances: list[dict],
        alb_result: dict,
    ) -> dict:
        """
        Retrieve CloudWatch alarms associated with discovered EC2 and ALB
        resources. The CloudWatch tool performs the dimension-based filtering.
        """
        instance_ids = [
            instance["instance_id"]
            for instance in instances
            if instance.get("instance_id")
        ]

        load_balancers = (
            alb_result.get("load_balancers", [])
            if alb_result.get("status") == "completed"
            else []
        )

        try:
            result = self._cloudwatch().get_alarms(
                instance_ids=instance_ids,
                load_balancers=load_balancers,
            )

            return {
                "status": result.get("status", "failed"),
                "scoped": result.get("scoped", True),
                "alarm_count": result.get("alarm_count", 0),
                "state_counts": result.get("state_counts", {}),
                "alarms": result.get("alarms", []),
            }

        except Exception as exc:
            logger.exception("CloudWatch alarm investigation failed")

            return {
                "status": "failed",
                "scoped": True,
                "alarm_count": 0,
                "state_counts": {},
                "alarms": [],
                "error": type(exc).__name__,
            }

    def _check_health_parallel(self) -> dict:
        # EC2, Kubernetes, and ALB discovery are independent.
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

        cloudwatch_alb_result = self._collect_cloudwatch_alb_health(
            alb_result
        )

        instances = ec2_result.get("instances", [])
        pods = kubernetes_result.get("pods", [])

        # Alarm collection uses the EC2 and ALB inventory already discovered.
        cloudwatch_alarms_result = self._collect_cloudwatch_alarms(
            instances=instances,
            alb_result=alb_result,
        )

        diagnosis = self.analyzer.analyze_runtime_health(
            instances=instances,
            pods=pods,
            cloudwatch_metrics=cloudwatch_result.get(
                "instance_metrics",
                [],
            ),
            alb_health=alb_result,
            cloudwatch_alb_metrics=cloudwatch_alb_result.get(
                "load_balancers",
                [],
            ),
            cloudwatch_alarms=cloudwatch_alarms_result.get(
                "alarms",
                [],
            ),
        )

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
                "Some EC2 CloudWatch metrics could not be collected completely."
            )

        if cloudwatch_alb_result["status"] in {"failed", "partial"}:
            diagnosis["evidence_gaps"].append(
                "Some ALB CloudWatch metrics could not be collected completely."
            )

        if cloudwatch_alarms_result["status"] in {"failed", "partial"}:
            diagnosis["evidence_gaps"].append(
                "CloudWatch alarm investigation could not be completed completely."
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

        primary_statuses = [
            ec2_result["status"],
            kubernetes_result["status"],
            alb_result["status"],
        ]

        successful_primary = sum(
            status == "completed"
            for status in primary_statuses
        )

        cloudwatch_statuses = [
            cloudwatch_result["status"],
            cloudwatch_alb_result["status"],
            cloudwatch_alarms_result["status"],
        ]

        cloudwatch_complete = all(
            status in {"completed", "skipped"}
            for status in cloudwatch_statuses
        )

        if successful_primary == 0:
            execution_status = "failed"

        elif (
            successful_primary == len(primary_statuses)
            and cloudwatch_complete
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
                {
                    "tool": "cloudwatch",
                    "action": "get_alb_metrics",
                    "status": cloudwatch_alb_result["status"],
                },
                {
                    "tool": "cloudwatch",
                    "action": "get_alarms",
                    "status": cloudwatch_alarms_result["status"],
                },
            ],
            "output": {
                "ec2": ec2_result,
                "kubernetes": kubernetes_result,
                "cloudwatch": cloudwatch_result,
                "alb": alb_result,
                "cloudwatch_alb": cloudwatch_alb_result,
                "cloudwatch_alarms": cloudwatch_alarms_result,
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

from app.agents.planner import DevOpsPlanner
from app.agents.analyzer import DevOpsAnalyzer
from app.config import Settings, get_settings
from app.tools.aws_cloudwatch_tool import CloudWatchTool
from app.tools.aws_ec2_tool import EC2Tool
from app.tools.kubernetes_tool import KubernetesTool


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
    ):
        self.settings = settings or get_settings()
        self.region = region or self.settings.aws_region
        self.planner = planner
        self.ec2_tool = ec2_tool
        self.cloudwatch_tool = cloudwatch_tool
        self.kubernetes_tool = kubernetes_tool
        self.analyzer = DevOpsAnalyzer()

    def _ec2(self) -> EC2Tool:
        if self.ec2_tool is None:
            self.ec2_tool = EC2Tool(region=self.region)
        return self.ec2_tool

    def _cloudwatch(self) -> CloudWatchTool:
        if self.cloudwatch_tool is None:
            self.cloudwatch_tool = CloudWatchTool(region=self.region)
        return self.cloudwatch_tool

    def _kubernetes(self) -> KubernetesTool:
        if self.kubernetes_tool is None:
            self.kubernetes_tool = KubernetesTool(
                namespace=self.settings.devops_kubernetes_namespace,
            )
        return self.kubernetes_tool

    def _validate_scope(self, environment: str, request_region: str | None) -> None:
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
            f"Environment: {environment}\nAWS region: {self.region}\n"
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

    def run(
        self,
        prompt: str,
        environment: str = "development",
        action: str = "plan",
        target_instance_id: str | None = None,
        request_region: str | None = None,
    ) -> dict:
        self._validate_scope(environment, request_region)

        # Actions come from the request's fixed enum, never from planner output.
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
                    {"tool": "ec2", "action": action, "args": {}}
                ],
                "output": result,
            }

        if action == "get_instance_cpu":
            if not target_instance_id:
                raise ValueError("target_instance_id is required.")
            self._get_scoped_instance(target_instance_id)
            result = self._cloudwatch().get_instance_cpu(target_instance_id)
            return {
                "status": "completed",
                "intent": action,
                "summary": f"Retrieved CloudWatch CPU metrics for {target_instance_id}.",
                "tool_calls": [
                    {
                        "tool": "cloudwatch",
                        "action": action,
                        "args": {"instance_id": target_instance_id},
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
            tag_key, tag_value = self._target_tag()
            ec2_result = self._ec2().list_instances(
                tag_key=tag_key,
                tag_value=tag_value,
            )
            pod_result = self._kubernetes().list_pods()
            diagnosis = self.analyzer.analyze_runtime_health(
                instances=ec2_result["instances"],
                pods=pod_result["pods"],
            )
            return {
                "status": "completed",
                "intent": action,
                "summary": diagnosis["conclusion"],
                "tool_calls": [
                    {
                        "tool": "ec2",
                        "action": "list_instances",
                        "args": {"tag": {tag_key: tag_value}},
                    },
                    {
                        "tool": "kubernetes",
                        "action": "list_pods",
                        "args": {
                            "namespace": self.settings.devops_kubernetes_namespace
                        },
                    },
                ],
                "output": {
                    "ec2": ec2_result,
                    "kubernetes": pod_result,
                    "diagnosis": diagnosis,
                },
            }

        if action == "stop_instance":
            return self._stop_instance(target_instance_id)

        # Never dispatch model-produced or otherwise unknown action names.
        raise AgentPolicyError("The requested action is not allowlisted.")

    def _stop_instance(self, instance_id: str | None) -> dict:
        if not instance_id:
            raise ValueError("target_instance_id is required.")
        if "stop_instance" not in self.settings.allowed_ec2_actions:
            raise AgentPolicyError(
                "EC2 stop is disabled; add stop_instance to "
                "DEVOPS_ALLOWED_EC2_ACTIONS to enable it."
            )

        # Check live AWS tags immediately before the mutation; do not trust prompt claims.
        instance = self._get_scoped_instance(instance_id)
        if instance["state"] != "running":
            raise AgentPolicyError(
                "Only running EC2 instances can be stopped by this agent."
            )

        result = self._ec2().stop_instance(instance_id)
        return {
            "status": "completed",
            "intent": "stop_instance",
            "summary": f"Submitted a stop request for EC2 instance {instance_id}.",
            "tool_calls": [
                {
                    "tool": "ec2",
                    "action": "stop_instance",
                    "args": {"instance_id": instance_id},
                }
            ],
            "output": result,
        }

    def _target_tag(self) -> tuple[str, str]:
        tag_key = self.settings.devops_target_tag_key
        tag_value = self.settings.devops_target_tag_value
        if not tag_key or not tag_value:
            raise AgentPolicyError(
                "AWS resource access is disabled until the target tag key and value are configured."
            )
        return tag_key, tag_value

    def _get_scoped_instance(self, instance_id: str) -> dict:
        tag_key, tag_value = self._target_tag()
        instance = self._ec2().get_instance(instance_id)
        if instance is None:
            raise LookupError("The requested EC2 instance was not found.")
        if instance["tags"].get(tag_key) != tag_value:
            raise AgentPolicyError(
                "The EC2 instance does not match the configured target tag."
            )
        return instance
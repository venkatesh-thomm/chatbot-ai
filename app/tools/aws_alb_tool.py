import boto3

from app.config import get_settings

from botocore.config import Config

aws_config = Config(
    connect_timeout=3,
    read_timeout=10,
    retries={
        "max_attempts": 2,
        "mode": "standard"
    }
)


class AWSALBReadOnlyTool:

    def __init__(self):
        settings = get_settings()
        self.region = settings.aws_region

        self.client = boto3.client(
            "elbv2",
            region_name=self.region,
        )

    def inspect_load_balancers(self, request: str = "") -> dict:
        load_balancers = []
        target_groups = []

        paginator = self.client.get_paginator(
            "describe_load_balancers"
        )

        for page in paginator.paginate():
            load_balancers.extend(
                page.get("LoadBalancers", [])
            )

        for lb in load_balancers:
            listeners = self.client.describe_listeners(
                LoadBalancerArn=lb["LoadBalancerArn"]
            ).get("Listeners", [])

            groups = self.client.describe_target_groups(
                LoadBalancerArn=lb["LoadBalancerArn"]
            ).get("TargetGroups", [])

            lb["Listeners"] = [
                {
                    "port": listener.get("Port"),
                    "protocol": listener.get("Protocol"),
                    "default_actions": listener.get(
                        "DefaultActions", []
                    ),
                }
                for listener in listeners
            ]

            for group in groups:
                health = self.client.describe_target_health(
                    TargetGroupArn=group["TargetGroupArn"]
                ).get("TargetHealthDescriptions", [])

                target_groups.append({
                    "load_balancer_name": lb["LoadBalancerName"],
                    "target_group_arn": group["TargetGroupArn"],
                    "target_group_name": group["TargetGroupName"],
                    "protocol": group.get("Protocol"),
                    "port": group.get("Port"),
                    "target_type": group.get("TargetType"),
                    "health_check_path": group.get("HealthCheckPath"),
                    "targets": [
                        {
                            "target_id": item["Target"]["Id"],
                            "port": item["Target"].get("Port"),
                            "availability_zone": item["Target"].get(
                                "AvailabilityZone"
                            ),
                            "state": item["TargetHealth"]["State"],
                            "reason": item["TargetHealth"].get("Reason"),
                            "description": item["TargetHealth"].get(
                                "Description"
                            ),
                        }
                        for item in health
                    ],
                })

        return {
            "tool": "aws_alb_read_only",
            "region": self.region,
            "load_balancer_count": len(load_balancers),
            "load_balancers": load_balancers,
            "target_groups": target_groups,
        }
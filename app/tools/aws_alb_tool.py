import boto3
from botocore.exceptions import ClientError


class ALBTool:
    def __init__(self, region: str | None = None):
        self.region = region
        self.elbv2 = boto3.client("elbv2", region_name=region)

    def list_load_balancers(self):
        try:
            paginator = self.elbv2.get_paginator("describe_load_balancers")
            load_balancers = [
                load_balancer
                for page in paginator.paginate()
                for load_balancer in page.get("LoadBalancers", [])
            ]
            return {"load_balancers": load_balancers}
        except ClientError as exc:
            raise RuntimeError(f"ALB describe_load_balancers failed: {exc}") from exc

    def get_targets(self, target_group_arn: str):
        try:
            resp = self.elbv2.describe_target_health(
                TargetGroupArn=target_group_arn
            )
            return {"targets": resp.get("TargetHealthDescriptions", [])}
        except ClientError as exc:
            raise RuntimeError(f"ALB target health failed: {exc}") from exc
from datetime import datetime, timedelta, timezone

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



class AWSCloudWatchReadOnlyTool:
    def __init__(self):
        settings = get_settings()
        self.region = settings.aws_region
        self.client = boto3.client(
            "cloudwatch",
            region_name=self.region,
        )

    def get_metric(
        self,
        namespace: str,
        metric_name: str,
        dimensions: list,
        period: int = 300,
    ) -> dict:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=1)

        response = self.client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=["Average", "Maximum", "Sum"],
        )

        datapoints = sorted(
            response.get("Datapoints", []),
            key=lambda item: item["Timestamp"],
        )

        return {
            "metric": metric_name,
            "datapoints": [
                {
                    "timestamp": point["Timestamp"].isoformat(),
                    "average": point.get("Average"),
                    "maximum": point.get("Maximum"),
                    "sum": point.get("Sum"),
                    "unit": point.get("Unit"),
                }
                for point in datapoints
            ],
        }

    def inspect_alb_metrics(
        self,
        load_balancer_arn: str,
        target_group_arn: str | None = None,
    ) -> dict:
        lb_dimension = load_balancer_arn.split(
            "loadbalancer/", 1
        )[-1]

        lb_metrics = [
            "HTTPCode_ELB_5XX_Count",
            "HTTPCode_Target_5XX_Count",
            "TargetResponseTime",
        ]

        metrics = {}

        for metric in lb_metrics:
            metrics[metric] = self.get_metric(
                namespace="AWS/ApplicationELB",
                metric_name=metric,
                dimensions=[
                    {"Name": "LoadBalancer", "Value": lb_dimension}
                ],
            )

        if target_group_arn:
            tg_dimension = target_group_arn.split(
                "targetgroup/", 1
            )[-1]

            for metric in [
                "HealthyHostCount",
                "UnHealthyHostCount",
            ]:
                metrics[metric] = self.get_metric(
                    namespace="AWS/ApplicationELB",
                    metric_name=metric,
                    dimensions=[
                        {"Name": "LoadBalancer", "Value": lb_dimension},
                        {"Name": "TargetGroup", "Value": tg_dimension},
                    ],
                )

        return metrics

    def inspect_ec2_metrics(self, instance_id: str) -> dict:
        metrics = {}

        for metric in [
            "CPUUtilization",
            "StatusCheckFailed",
            "StatusCheckFailed_Instance",
            "StatusCheckFailed_System",
        ]:
            metrics[metric] = self.get_metric(
                namespace="AWS/EC2",
                metric_name=metric,
                dimensions=[
                    {"Name": "InstanceId", "Value": instance_id}
                ],
            )

        return metrics
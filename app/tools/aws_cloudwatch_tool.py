from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


class CloudWatchTool:
    def __init__(self, region: str | None = None):
        self.region = region
        self.client = boto3.client("cloudwatch", region_name=region)

    def get_instance_cpu(self, instance_id: str, period: int = 300):
        if period <= 0 or period % 60 != 0:
            raise ValueError("period must be a positive multiple of 60 seconds.")

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=1)
        try:
            response = self.client.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=["Average", "Maximum"],
            )
            return {"instance_id": instance_id, "datapoints": response.get("Datapoints", [])}
        except ClientError as exc:
            raise RuntimeError(f"CloudWatch get_metric_statistics failed: {exc}") from exc

    def get_alarms(self):
        try:
            resp = self.client.describe_alarms()
            return {"alarms": resp.get("MetricAlarms", [])}
        except ClientError as exc:
            raise RuntimeError(f"CloudWatch describe_alarms failed: {exc}") from exc
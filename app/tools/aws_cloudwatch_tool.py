
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


class CloudWatchTool:
    def __init__(self, region: str | None = None):
        self.region = region
        self.client = boto3.client(
            "cloudwatch",
            region_name=region,
        )

    def _time_range(self):
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=1)
        return start_time, end_time

    def get_instance_cpu(
        self,
        instance_id: str,
        period: int = 300,
    ) -> dict:
        if period <= 0 or period % 60 != 0:
            raise ValueError(
                "period must be a positive multiple of 60 seconds."
            )

        start_time, end_time = self._time_range()

        try:
            response = self.client.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[
                    {"Name": "InstanceId", "Value": instance_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=["Average", "Maximum"],
            )

            datapoints = sorted(
                response.get("Datapoints", []),
                key=lambda item: item["Timestamp"],
            )

            return {
                "instance_id": instance_id,
                "metric": "CPUUtilization",
                "datapoints": datapoints,
            }

        except ClientError as exc:
            raise RuntimeError(
                f"CloudWatch CPU retrieval failed: {exc}"
            ) from exc

    def get_instance_health_metrics(
        self,
        instance_id: str,
        period: int = 300,
    ) -> dict:
        if period <= 0 or period % 60 != 0:
            raise ValueError(
                "period must be a positive multiple of 60 seconds."
            )

        start_time, end_time = self._time_range()

        metric_definitions = {
            "cpu_utilization": "CPUUtilization",
            "status_check_failed": "StatusCheckFailed",
            "status_check_failed_instance": "StatusCheckFailed_Instance",
            "status_check_failed_system": "StatusCheckFailed_System",
        }

        queries = []

        for query_id, metric_name in metric_definitions.items():
            queries.append({
                "Id": query_id,
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/EC2",
                        "MetricName": metric_name,
                        "Dimensions": [
                            {
                                "Name": "InstanceId",
                                "Value": instance_id,
                            }
                        ],
                    },
                    "Period": period,
                    "Stat": "Maximum",
                },
                "ReturnData": True,
            })

        try:
            response = self.client.get_metric_data(
                MetricDataQueries=queries,
                StartTime=start_time,
                EndTime=end_time,
                ScanBy="TimestampAscending",
            )

            query_to_metric = {
                query_id: metric_name
                for query_id, metric_name in metric_definitions.items()
            }

            metrics = {
                metric_name: {
                    "datapoints": [],
                    "status_code": "NoData",
                }
                for metric_name in metric_definitions.values()
            }

            for result in response.get("MetricDataResults", []):
                metric_name = query_to_metric.get(result["Id"])

                if not metric_name:
                    continue

                timestamps = result.get("Timestamps", [])
                values = result.get("Values", [])

                datapoints = [
                    {
                        "timestamp": timestamp.isoformat(),
                        "maximum": value,
                    }
                    for timestamp, value in zip(timestamps, values)
                ]

                datapoints.sort(
                    key=lambda point: point["timestamp"]
                )

                metrics[metric_name] = {
                    "datapoints": datapoints,
                    "status_code": result.get("StatusCode"),
                    "messages": result.get("Messages", []),
                }

            return {
                "instance_id": instance_id,
                "metrics": metrics,
            }

        except ClientError as exc:
            raise RuntimeError(
                f"CloudWatch health metrics retrieval failed: {exc}"
            ) from exc

    def get_alarms(self) -> dict:
        try:
            response = self.client.describe_alarms()

            return {
                "alarms": response.get("MetricAlarms", [])
            }

        except ClientError as exc:
            raise RuntimeError(
                f"CloudWatch describe_alarms failed: {exc}"
            ) from exc

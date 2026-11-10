
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError


class CloudWatchTool:

    METRIC_DEFINITIONS = {
        "cpu_utilization": "CPUUtilization",
        "status_check_failed": "StatusCheckFailed",
        "status_check_failed_instance": "StatusCheckFailed_Instance",
        "status_check_failed_system": "StatusCheckFailed_System",
    }

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

        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"CloudWatch CPU retrieval failed: {type(exc).__name__}"
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

        queries = []

        for query_id, metric_name in self.METRIC_DEFINITIONS.items():
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

        query_results = {
            query_id: {
                "timestamps": [],
                "values": [],
                "status_codes": [],
                "messages": [],
            }
            for query_id in self.METRIC_DEFINITIONS
        }

        request = {
            "MetricDataQueries": queries,
            "StartTime": start_time,
            "EndTime": end_time,
            "ScanBy": "TimestampAscending",
        }

        seen_tokens = set()

        try:
            # Retrieve all pages instead of silently ignoring NextToken.
            while True:
                response = self.client.get_metric_data(**request)

                for result in response.get("MetricDataResults", []):
                    query_id = result.get("Id")

                    if query_id not in query_results:
                        continue

                    accumulator = query_results[query_id]

                    accumulator["status_codes"].append(
                        result.get("StatusCode", "MissingStatus")
                    )

                    accumulator["messages"].extend(
                        result.get("Messages", [])
                    )

                    timestamps = result.get("Timestamps", [])
                    values = result.get("Values", [])

                    if len(timestamps) != len(values):
                        accumulator["status_codes"].append(
                            "InvalidResponse"
                        )
                        accumulator["messages"].append(
                            "CloudWatch returned mismatched timestamps and values."
                        )

                    for timestamp, value in zip(timestamps, values):
                        timestamp_value = (
                            timestamp.isoformat()
                            if hasattr(timestamp, "isoformat")
                            else str(timestamp)
                        )

                        accumulator["timestamps"].append(timestamp_value)
                        accumulator["values"].append(value)

                next_token = response.get("NextToken")

                if not next_token:
                    break

                if next_token in seen_tokens:
                    raise RuntimeError(
                        "CloudWatch returned a repeated pagination token."
                    )

                seen_tokens.add(next_token)
                request["NextToken"] = next_token

        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"CloudWatch health metrics retrieval failed: "
                f"{type(exc).__name__}"
            ) from exc

        query_to_metric = {
            query_id: metric_name
            for query_id, metric_name in self.METRIC_DEFINITIONS.items()
        }

        metrics = {}

        for query_id, accumulator in query_results.items():
            status_codes = accumulator["status_codes"]

            if not status_codes:
                status_code = "MissingResult"

            elif all(code == "Complete" for code in status_codes):
                status_code = "Complete"

            elif "PartialData" in status_codes:
                status_code = "PartialData"

            else:
                status_code = next(
                    (
                        code for code in status_codes
                        if code != "Complete"
                    ),
                    "Unknown",
                )

            datapoints = [
                {
                    "timestamp": timestamp,
                    "maximum": value,
                }
                for timestamp, value in zip(
                    accumulator["timestamps"],
                    accumulator["values"],
                )
            ]

            datapoints.sort(
                key=lambda point: point["timestamp"]
            )

            metric_name = query_to_metric[query_id]

            metrics[metric_name] = {
                "datapoints": datapoints,
                "status_code": status_code,
                "messages": accumulator["messages"],
            }

        metric_statuses = [
            metric["status_code"]
            for metric in metrics.values()
        ]

        if all(
            status == "Complete"
            for status in metric_statuses
        ):
            overall_status = "completed"

        elif any(
            status in {"Complete", "PartialData"}
            for status in metric_statuses
        ):
            overall_status = "partial"

        else:
            overall_status = "failed"

        return {
            "instance_id": instance_id,
            "status": overall_status,
            "metrics": metrics,
        }

    def get_alarms(self) -> dict:
        try:
            response = self.client.describe_alarms()

            return {
                "alarms": response.get("MetricAlarms", [])
            }

        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"CloudWatch alarm retrieval failed: {type(exc).__name__}"
            ) from exc

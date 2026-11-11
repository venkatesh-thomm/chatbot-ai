
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

    @staticmethod
    def _validate_period(period: int) -> None:
        if period <= 0 or period % 60 != 0:
            raise ValueError(
                "period must be a positive multiple of 60 seconds."
            )

    @staticmethod
    def _arn_dimension_value(
        arn: str,
        resource_marker: str,
    ) -> str:
        if resource_marker not in arn:
            raise ValueError(
                f"Invalid AWS ARN. Expected resource type: {resource_marker}"
            )

        return arn.split(resource_marker, 1)[1]

    @staticmethod
    def _stat_field(statistic: str) -> str:
        return statistic.lower()

    def _execute_metric_queries(
        self,
        queries: list[dict],
        operation_name: str,
    ) -> dict:
        start_time, end_time = self._time_range()

        query_results = {
            query["Id"]: {
                "points": {},
                "status_codes": [],
                "messages": [],
                "statistic": query["MetricStat"]["Stat"],
            }
            for query in queries
        }

        request = {
            "MetricDataQueries": queries,
            "StartTime": start_time,
            "EndTime": end_time,
            "ScanBy": "TimestampAscending",
        }

        seen_tokens = set()

        try:
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

                        accumulator["points"][timestamp_value] = value

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
                f"CloudWatch {operation_name} failed: "
                f"{type(exc).__name__}"
            ) from exc

        metrics = {}

        for query_id, accumulator in query_results.items():
            status_codes = accumulator["status_codes"]

            if not status_codes:
                status_code = "MissingResult"

            elif all(code == "Complete" for code in status_codes):
                status_code = "Complete"

            elif any(
                code in {"Complete", "PartialData"}
                for code in status_codes
            ):
                status_code = "PartialData"

            else:
                status_code = status_codes[0]

            statistic_field = self._stat_field(
                accumulator["statistic"]
            )

            datapoints = [
                {
                    "timestamp": timestamp,
                    statistic_field: value,
                }
                for timestamp, value in sorted(
                    accumulator["points"].items()
                )
            ]

            metrics[query_id] = {
                "datapoints": datapoints,
                "status_code": status_code,
                "messages": accumulator["messages"],
            }

        statuses = [
            metric["status_code"]
            for metric in metrics.values()
        ]

        if statuses and all(
            status == "Complete"
            for status in statuses
        ):
            overall_status = "completed"

        elif any(
            status in {"Complete", "PartialData"}
            for status in statuses
        ):
            overall_status = "partial"

        else:
            overall_status = "failed"

        return {
            "status": overall_status,
            "metrics": metrics,
        }

    def get_instance_cpu(
        self,
        instance_id: str,
        period: int = 300,
    ) -> dict:
        self._validate_period(period)

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
        self._validate_period(period)

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

        result = self._execute_metric_queries(
            queries,
            operation_name=f"EC2 health metrics for {instance_id}",
        )

        metrics = {
            metric_name: result["metrics"][query_id]
            for query_id, metric_name in self.METRIC_DEFINITIONS.items()
        }

        return {
            "instance_id": instance_id,
            "status": result["status"],
            "metrics": metrics,
        }

    def get_alb_metrics(
        self,
        load_balancer_arn: str,
        target_groups: list[dict] | None = None,
        period: int = 60,
    ) -> dict:
        self._validate_period(period)

        load_balancer_dimension = self._arn_dimension_value(
            load_balancer_arn,
            "loadbalancer/",
        )

        target_groups = target_groups or []

        queries = []
        query_metadata = {}

        queries.append({
            "Id": "elb_5xx",
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/ApplicationELB",
                    "MetricName": "HTTPCode_ELB_5XX_Count",
                    "Dimensions": [
                        {
                            "Name": "LoadBalancer",
                            "Value": load_balancer_dimension,
                        }
                    ],
                },
                "Period": period,
                "Stat": "Sum",
            },
            "ReturnData": True,
        })

        query_metadata["elb_5xx"] = {
            "level": "load_balancer",
            "metric_name": "HTTPCode_ELB_5XX_Count",
        }

        target_metric_definitions = [
            (
                "target_5xx",
                "HTTPCode_Target_5XX_Count",
                "Sum",
            ),
            (
                "target_response_time",
                "TargetResponseTime",
                "Average",
            ),
            (
                "healthy_hosts",
                "HealthyHostCount",
                "Minimum",
            ),
            (
                "unhealthy_hosts",
                "UnHealthyHostCount",
                "Maximum",
            ),
        ]

        for index, target_group in enumerate(target_groups):
            target_group_arn = target_group.get("target_group_arn")

            if not target_group_arn:
                raise ValueError(
                    "Every target group must contain target_group_arn."
                )

            target_group_dimension = self._arn_dimension_value(
                target_group_arn,
                "targetgroup/",
            )

            for query_suffix, metric_name, statistic in target_metric_definitions:
                query_id = f"tg{index}_{query_suffix}"

                queries.append({
                    "Id": query_id,
                    "MetricStat": {
                        "Metric": {
                            "Namespace": "AWS/ApplicationELB",
                            "MetricName": metric_name,
                            "Dimensions": [
                                {
                                    "Name": "LoadBalancer",
                                    "Value": load_balancer_dimension,
                                },
                                {
                                    "Name": "TargetGroup",
                                    "Value": target_group_dimension,
                                },
                            ],
                        },
                        "Period": period,
                        "Stat": statistic,
                    },
                    "ReturnData": True,
                })

                query_metadata[query_id] = {
                    "level": "target_group",
                    "target_group_arn": target_group_arn,
                    "target_group_name": target_group.get(
                        "target_group_name"
                    ),
                    "metric_name": metric_name,
                }

        result = self._execute_metric_queries(
            queries,
            operation_name=f"ALB metrics for {load_balancer_dimension}",
        )

        load_balancer_metrics = {}
        target_group_metrics = {}

        for query_id, metadata in query_metadata.items():
            metric_name = metadata["metric_name"]
            metric_result = result["metrics"][query_id]

            if metadata["level"] == "load_balancer":
                load_balancer_metrics[metric_name] = metric_result
                continue

            target_group_arn = metadata["target_group_arn"]

            if target_group_arn not in target_group_metrics:
                target_group_metrics[target_group_arn] = {
                    "target_group_arn": target_group_arn,
                    "target_group_name": metadata["target_group_name"],
                    "metrics": {},
                }

            target_group_metrics[target_group_arn]["metrics"][
                metric_name
            ] = metric_result

        return {
            "load_balancer_arn": load_balancer_arn,
            "status": result["status"],
            "load_balancer_metrics": load_balancer_metrics,
            "target_group_metrics": list(
                target_group_metrics.values()
            ),
        }

    @staticmethod
    def _alarm_timestamp(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    @staticmethod
    def _build_alarm_scope(
        instance_ids: list[str] | None,
        load_balancers: list[dict] | None,
    ) -> dict[str, set[str]]:
        scope = {
            "InstanceId": set(instance_ids or []),
            "LoadBalancer": set(),
            "TargetGroup": set(),
        }

        for load_balancer in load_balancers or []:
            load_balancer_arn = load_balancer.get("load_balancer_arn")

            if load_balancer_arn:
                scope["LoadBalancer"].add(
                    CloudWatchTool._arn_dimension_value(
                        load_balancer_arn,
                        "loadbalancer/",
                    )
                )

            for target_group in load_balancer.get("target_groups", []):
                target_group_arn = target_group.get("target_group_arn")

                if target_group_arn:
                    scope["TargetGroup"].add(
                        CloudWatchTool._arn_dimension_value(
                            target_group_arn,
                            "targetgroup/",
                        )
                    )

        return scope

    @staticmethod
    def _alarm_matches_scope(
        alarm: dict,
        scope: dict[str, set[str]],
    ) -> bool:
        dimensions = alarm.get("Dimensions", [])

        relevant_dimensions = [
            dimension
            for dimension in dimensions
            if dimension.get("Name") in scope
            and scope[dimension["Name"]]
        ]

        if not relevant_dimensions:
            return False

        # Every recognized resource dimension must belong to this run's scope.
        return all(
            dimension.get("Value") in scope[dimension["Name"]]
            for dimension in relevant_dimensions
        )

    @staticmethod
    def _normalize_alarm(alarm: dict) -> dict:
        return {
            "alarm_name": alarm.get("AlarmName"),
            "alarm_arn": alarm.get("AlarmArn"),
            "alarm_description": alarm.get("AlarmDescription"),
            "state_value": alarm.get("StateValue"),
            "state_reason": alarm.get("StateReason"),
            "state_updated_timestamp": CloudWatchTool._alarm_timestamp(
                alarm.get("StateUpdatedTimestamp")
            ),
            "namespace": alarm.get("Namespace"),
            "metric_name": alarm.get("MetricName"),
            "dimensions": [
                {
                    "name": dimension.get("Name"),
                    "value": dimension.get("Value"),
                }
                for dimension in alarm.get("Dimensions", [])
            ],
            "comparison_operator": alarm.get("ComparisonOperator"),
            "threshold": alarm.get("Threshold"),
            "evaluation_periods": alarm.get("EvaluationPeriods"),
            "datapoints_to_alarm": alarm.get("DatapointsToAlarm"),
            "period": alarm.get("Period"),
            "statistic": alarm.get("Statistic"),
            "extended_statistic": alarm.get("ExtendedStatistic"),
            "treat_missing_data": alarm.get("TreatMissingData"),
            "actions_enabled": alarm.get("ActionsEnabled"),
        }

    def get_alarms(
        self,
        instance_ids: list[str] | None = None,
        load_balancers: list[dict] | None = None,
    ) -> dict:
        """
        Retrieve metric alarms, optionally limited to discovered resources.

        When resource identifiers are supplied, only alarms whose recognized
        EC2 or ALB dimensions match the investigation scope are returned.
        Composite alarms are intentionally not included because they do not
        expose resource dimensions suitable for this direct matching.
        """
        scoped = instance_ids is not None or load_balancers is not None

        scope = self._build_alarm_scope(
            instance_ids=instance_ids,
            load_balancers=load_balancers,
        )

        alarms = []
        next_token = None
        seen_tokens = set()

        try:
            while True:
                request = {
                    "AlarmTypes": ["MetricAlarm"],
                    "MaxRecords": 100,
                }

                if next_token:
                    request["NextToken"] = next_token

                response = self.client.describe_alarms(**request)

                alarms.extend(
                    response.get("MetricAlarms", [])
                )

                next_token = response.get("NextToken")

                if not next_token:
                    break

                if next_token in seen_tokens:
                    raise RuntimeError(
                        "CloudWatch returned a repeated alarm pagination token."
                    )

                seen_tokens.add(next_token)

        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"CloudWatch alarm retrieval failed: {type(exc).__name__}"
            ) from exc

        if scoped:
            alarms = [
                alarm
                for alarm in alarms
                if self._alarm_matches_scope(alarm, scope)
            ]

        normalized_alarms = [
            self._normalize_alarm(alarm)
            for alarm in alarms
        ]

        normalized_alarms.sort(
            key=lambda alarm: (
                {
                    "ALARM": 0,
                    "INSUFFICIENT_DATA": 1,
                    "OK": 2,
                }.get(alarm.get("state_value"), 3),
                alarm.get("alarm_name") or "",
            )
        )

        state_counts = {
            "ALARM": 0,
            "INSUFFICIENT_DATA": 0,
            "OK": 0,
            "OTHER": 0,
        }

        for alarm in normalized_alarms:
            state = alarm.get("state_value")

            if state in state_counts:
                state_counts[state] += 1
            else:
                state_counts["OTHER"] += 1

        return {
            "status": "completed",
            "scoped": scoped,
            "alarm_count": len(normalized_alarms),
            "state_counts": state_counts,
            "alarms": normalized_alarms,
        }

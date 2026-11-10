class DevOpsAnalyzer:

    def _metric_values(self, metric_data: dict) -> list:
        return metric_data.get("datapoints", [])

    def _maximum(self, metric_data: dict):
        values = [
            point["maximum"]
            for point in self._metric_values(metric_data)
            if point.get("maximum") is not None
        ]
        return max(values) if values else None

    def _total(self, metric_data: dict):
        values = [
            point["sum"]
            for point in self._metric_values(metric_data)
            if point.get("sum") is not None
        ]
        return sum(values) if values else None

    def analyze(self, findings: list) -> dict:
        observations = []
        likely_causes = []
        evidence_available = False

        for item in findings:
            alb = item.get("alb", {})
            target_groups = alb.get("target_groups", [])

            for group in target_groups:
                for target in group.get("targets", []):
                    state = target.get("state")

                    if state == "unhealthy":
                        evidence_available = True
                        observations.append(
                            f"Target {target.get('target_id')} in "
                            f"{group.get('target_group_name')} is unhealthy. "
                            f"Reason: {target.get('reason') or 'Not provided'}."
                        )
                        likely_causes.append(
                            "One or more ALB targets are unhealthy. "
                            "Investigate application health checks, "
                            "target port, security groups and application availability."
                        )

            for entry in item.get("cloudwatch_alb_metrics", []):
                metrics = entry.get("metrics", {})

                for metric_name in [
                    "HTTPCode_ELB_5XX_Count",
                    "HTTPCode_Target_5XX_Count",
                ]:
                    metric = metrics.get(metric_name, {})
                    total = self._total(metric)

                    if total is not None:
                        evidence_available = True

                    if total is not None and total > 0:
                        observations.append(
                            f"{metric_name}: {total} errors during the "
                            "available CloudWatch observation period."
                        )
                        likely_causes.append(
                            f"{metric_name} is greater than zero. "
                            "Investigate the corresponding load balancer "
                            "or backend target errors."
                        )

                unhealthy = self._maximum(
                    metrics.get("UnHealthyHostCount", {})
                )
                healthy = self._maximum(
                    metrics.get("HealthyHostCount", {})
                )

                if unhealthy is not None:
                    evidence_available = True

                if unhealthy is not None and unhealthy > 0:
                    observations.append(
                        f"Unhealthy target count reached {unhealthy}."
                    )
                    likely_causes.append(
                        "Unhealthy targets may be contributing to "
                        "request failures."
                    )

                if healthy is not None:
                    evidence_available = True

                if healthy is not None and healthy == 0:
                    observations.append(
                        "Healthy target count reached zero."
                    )
                    likely_causes.append(
                        "No healthy targets were available for the load balancer."
                    )

                response_time = self._maximum(
                    metrics.get("TargetResponseTime", {})
                )

                if response_time is not None:
                    evidence_available = True

                if response_time is not None and response_time > 1:
                    observations.append(
                        f"Target response time reached {response_time} seconds."
                    )
                    likely_causes.append(
                        "Backend response latency is elevated. "
                        "Investigate application performance and dependencies."
                    )

            for entry in item.get("cloudwatch_ec2_metrics", []):
                instance_id = entry.get("instance_id")
                metrics = entry.get("metrics", {})

                for metric_name in [
                    "StatusCheckFailed",
                    "StatusCheckFailed_Instance",
                    "StatusCheckFailed_System",
                ]:
                    maximum = self._maximum(
                        metrics.get(metric_name, {})
                    )

                    if maximum is not None:
                        evidence_available = True

                    if maximum is not None and maximum > 0:
                        observations.append(
                            f"EC2 {instance_id}: {metric_name} reached "
                            f"{maximum}."
                        )
                        likely_causes.append(
                            f"EC2 instance {instance_id} has a failed "
                            "status check. Investigate instance or "
                            "underlying AWS infrastructure health."
                        )

                cpu = self._maximum(
                    metrics.get("CPUUtilization", {})
                )

                if cpu is not None:
                    evidence_available = True

                if cpu is not None and cpu >= 80:
                    observations.append(
                        f"EC2 {instance_id}: CPU utilization reached "
                        f"{cpu}%."
                    )
                    likely_causes.append(
                        f"EC2 instance {instance_id} has high CPU utilization."
                    )

        # Remove duplicate causes while preserving order.
        likely_causes = list(dict.fromkeys(likely_causes))

        if not evidence_available:
            status = "insufficient_metrics"
            conclusion = (
                "No usable CloudWatch metric datapoints or target-health "
                "evidence were available. Root cause cannot yet be determined."
            )
        elif likely_causes:
            status = "potential_issues_detected"
            conclusion = (
                "Potential infrastructure or backend issues were detected. "
                "The findings are evidence-based indicators, not a confirmed "
                "root cause."
            )
        else:
            status = "no_obvious_issue_detected"
            conclusion = (
                "No obvious issue was detected in the collected findings. "
                "This does not rule out application-level or intermittent failures."
            )

        return {
            "status": status,
            "conclusion": conclusion,
            "observations": observations,
            "likely_causes": likely_causes,
            "evidence_available": evidence_available,
        }
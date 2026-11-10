class DevOpsAnalyzer:

    def analyze_runtime_health(
        self,
        *,
        instances: list[dict] | None = None,
        pods: list[dict] | None = None,
    ) -> dict:
        """Explain unhealthy signals from observed EC2 and pod status only."""
        observations = []
        possible_causes = []
        evidence_gaps = []
        checked_resources = 0

        for instance in instances or []:
            checked_resources += 1
            instance_id = instance.get("instance_id", "unknown")
            state = instance.get("state", "unknown")

            if state != "running":
                reason = instance.get("state_reason")
                observations.append(
                    f"EC2 instance {instance_id} is {state}."
                    + (f" AWS reports: {reason}" if reason else "")
                )
                possible_causes.append(
                    "The instance is not running. Its state reason may indicate "
                    "whether it was stopped by a user, an AWS event, or a failure; "
                    "check CloudTrail and the EC2 console for more detail."
                )

            checks = instance.get("status_checks") or {}
            if not checks:
                evidence_gaps.append(
                    f"EC2 status checks were unavailable for {instance_id}."
                )
            for check_name in ("instance_status", "system_status"):
                check_status = checks.get(check_name)
                if check_status == "impaired":
                    observations.append(
                        f"EC2 instance {instance_id} {check_name.replace('_', ' ')} "
                        f"is {check_status}."
                    )
                    possible_causes.append(
                        "An EC2 status check is impaired or still initializing. "
                        "Inspect the EC2 status-check details and system log."
                    )
                elif check_status == "initializing":
                    evidence_gaps.append(
                        f"EC2 {check_name.replace('_', ' ')} for {instance_id} "
                        "is still initializing."
                    )
                elif check_status not in {"ok", "not-applicable"}:
                    evidence_gaps.append(
                        f"EC2 {check_name.replace('_', ' ')} for {instance_id} "
                        "did not return a definitive status."
                    )

            for event in checks.get("events", []):
                observations.append(
                    f"EC2 instance {instance_id} has scheduled event "
                    f"{event.get('code') or 'unknown'}: "
                    f"{event.get('description') or 'description unavailable'}."
                )

        for pod in pods or []:
            checked_resources += 1
            pod_name = pod.get("name", "unknown")
            namespace = pod.get("namespace", "unknown")

            if pod.get("phase") == "Failed":
                observations.append(
                    f"Pod {namespace}/{pod_name} is in Failed phase."
                )
                possible_causes.append(
                    "The pod terminated unsuccessfully. Inspect its container "
                    "termination reason and Kubernetes events."
                )
            elif pod.get("phase") != "Succeeded" and not pod.get("ready", False):
                observations.append(
                    f"Pod {namespace}/{pod_name} is not ready "
                    f"(phase: {pod.get('phase', 'Unknown')})."
                )
                possible_causes.append(
                    "The pod may be waiting for scheduling, image retrieval, "
                    "container startup, or a readiness probe."
                )

            if pod.get("restart_count", 0) > 0:
                observations.append(
                    f"Pod {namespace}/{pod_name} has restarted "
                    f"{pod['restart_count']} time(s)."
                )
                possible_causes.append(
                    "Container restarts can result from crashes, failed probes, "
                    "resource limits, or node issues; inspect container logs and "
                    "events to identify the cause."
                )

            for container in pod.get("containers", []):
                reason = container.get("reason")
                if reason:
                    observations.append(
                        f"Container {container.get('name', 'unknown')} in "
                        f"{namespace}/{pod_name} reports {reason}."
                    )

            for event in pod.get("warning_events", []):
                if event.get("reason") or event.get("message"):
                    observations.append(
                        f"Kubernetes warning for {namespace}/{pod_name}: "
                        f"{event.get('reason') or 'Warning'} — "
                        f"{event.get('message') or 'message unavailable'}."
                    )

        if observations:
            status = "issues_detected"
            conclusion = (
                "The following unhealthy signals were observed. Possible causes "
                "are investigative leads, not a confirmed root cause."
            )
        elif evidence_gaps or not checked_resources:
            status = "insufficient_evidence"
            conclusion = (
                "No unhealthy signal was confirmed, but the available health "
                "evidence is incomplete."
            )
        elif checked_resources:
            status = "healthy"
            conclusion = (
                "No unhealthy EC2 or pod signals were found in the inspected "
                "resources at check time."
            )
        else:
            status = "insufficient_evidence"
            conclusion = "No EC2 instances or Kubernetes pods were available to inspect."

        return {
            "status": status,
            "conclusion": conclusion,
            "checked_resource_count": checked_resources,
            "observations": observations,
            "possible_causes": list(dict.fromkeys(possible_causes)),
            "evidence_gaps": evidence_gaps,
        }

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
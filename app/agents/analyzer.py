class DevOpsAnalyzer:

    def analyze_runtime_health(
        self,
        *,
        instances: list[dict] | None = None,
        pods: list[dict] | None = None,
        cloudwatch_metrics: list[dict] | None = None,
        alb_health: dict | None = None,
    ) -> dict:
        observations = []
        possible_causes = []
        evidence_gaps = []
        checked_resources = 0

        # EC2 instance health
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
                    "The EC2 instance is not running. Inspect its state "
                    "reason and relevant AWS events."
                )

            checks = instance.get("status_checks") or {}

            if not checks:
                evidence_gaps.append(
                    f"EC2 status checks unavailable for {instance_id}."
                )

            for check_name in (
                "instance_status",
                "system_status",
            ):
                check_status = checks.get(check_name)

                if check_status == "impaired":
                    observations.append(
                        f"EC2 {instance_id}: "
                        f"{check_name.replace('_', ' ')} is impaired."
                    )

                    possible_causes.append(
                        "An EC2 instance or system status check is impaired. "
                        "Investigate instance health and AWS infrastructure."
                    )

                elif check_status == "initializing":
                    evidence_gaps.append(
                        f"EC2 {check_name} for {instance_id} "
                        "is still initializing."
                    )

                elif check_status not in {"ok", "not-applicable"}:
                    evidence_gaps.append(
                        f"EC2 {check_name} for {instance_id} "
                        "did not return a definitive status."
                    )

            for event in checks.get("events", []):
                observations.append(
                    f"EC2 {instance_id} has scheduled event "
                    f"{event.get('code') or 'unknown'}: "
                    f"{event.get('description') or 'description unavailable'}."
                )

        # Kubernetes Pod health
        for pod in pods or []:
            checked_resources += 1

            pod_name = pod.get("name", "unknown")
            namespace = pod.get("namespace", "unknown")
            phase = pod.get("phase", "Unknown")

            if phase == "Failed":
                observations.append(
                    f"Pod {namespace}/{pod_name} is in Failed phase."
                )

                possible_causes.append(
                    "The Kubernetes Pod terminated unsuccessfully. "
                    "Inspect container termination reason and events."
                )

            elif phase != "Succeeded" and not pod.get("ready", False):
                observations.append(
                    f"Pod {namespace}/{pod_name} is not ready "
                    f"(phase: {phase})."
                )

                possible_causes.append(
                    "The Pod may have scheduling, image pull, startup, "
                    "or readiness-probe problems."
                )

            restart_count = pod.get("restart_count", 0)

            if restart_count > 0:
                observations.append(
                    f"Pod {namespace}/{pod_name} has restarted "
                    f"{restart_count} time(s)."
                )

                possible_causes.append(
                    "Container restarts can result from application crashes, "
                    "failed probes, resource limits, or node issues."
                )

            for container in pod.get("containers", []):
                reason = container.get("reason")

                if reason:
                    observations.append(
                        f"Container {container.get('name', 'unknown')} "
                        f"in {namespace}/{pod_name} reports {reason}."
                    )

            for event in pod.get("warning_events", []):
                if event.get("reason") or event.get("message"):
                    observations.append(
                        f"Kubernetes warning for {namespace}/{pod_name}: "
                        f"{event.get('reason') or 'Warning'} - "
                        f"{event.get('message') or 'message unavailable'}."
                    )

        # CloudWatch EC2 metrics
        for item in cloudwatch_metrics or []:
            instance_id = item.get("instance_id", "unknown")

            if item.get("status") != "completed":
                evidence_gaps.append(
                    f"CloudWatch metrics unavailable for {instance_id}."
                )
                continue

            metrics = item.get("metrics", {})
            has_datapoints = False

            cpu_points = metrics.get(
                "CPUUtilization", {}
            ).get("datapoints", [])

            cpu_values = [
                point["maximum"]
                for point in cpu_points
                if point.get("maximum") is not None
            ]

            if cpu_values:
                has_datapoints = True
                maximum_cpu = max(cpu_values)

                if maximum_cpu >= 80:
                    observations.append(
                        f"EC2 {instance_id} CPU utilization "
                        f"reached {maximum_cpu}%."
                    )

                    possible_causes.append(
                        f"EC2 instance {instance_id} has high CPU utilization. "
                        "Investigate workload and application resource consumption."
                    )

            status_metrics = [
                "StatusCheckFailed",
                "StatusCheckFailed_Instance",
                "StatusCheckFailed_System",
            ]

            for metric_name in status_metrics:
                points = metrics.get(
                    metric_name, {}
                ).get("datapoints", [])

                values = [
                    point["maximum"]
                    for point in points
                    if point.get("maximum") is not None
                ]

                if not values:
                    continue

                has_datapoints = True
                maximum = max(values)

                if maximum > 0:
                    observations.append(
                        f"EC2 {instance_id}: {metric_name} "
                        f"reached {maximum}."
                    )

                    possible_causes.append(
                        f"EC2 instance {instance_id} reported {metric_name}. "
                        "Investigate EC2 status-check details."
                    )

            if not has_datapoints:
                evidence_gaps.append(
                    f"No CloudWatch datapoints were available for {instance_id}."
                )

        # Application Load Balancer and target health
        if alb_health is not None:
            alb_status = alb_health.get("status")

            if alb_status != "completed":
                evidence_gaps.append(
                    "ALB investigation could not be completed. "
                    f"Status: {alb_status or 'unknown'}."
                )

            else:
                load_balancers = alb_health.get(
                    "load_balancers",
                    [],
                )

                if not load_balancers:
                    evidence_gaps.append(
                        "No Application Load Balancers were found "
                        "in the configured AWS region."
                    )

                for load_balancer in load_balancers:
                    checked_resources += 1

                    lb_name = load_balancer.get(
                        "name",
                        "unknown",
                    )
                    lb_state = load_balancer.get("state")

                    if lb_state == "active_impaired":
                        observations.append(
                            f"Application Load Balancer {lb_name} "
                            "is in active_impaired state."
                        )

                        possible_causes.append(
                            "The load balancer is active but impaired. "
                            "Inspect its AWS state reason, listeners, "
                            "target groups, and network configuration."
                        )

                    elif lb_state == "failed":
                        observations.append(
                            f"Application Load Balancer {lb_name} "
                            "is in failed state."
                        )

                        possible_causes.append(
                            "The Application Load Balancer has entered "
                            "a failed state. Inspect its AWS state reason."
                        )

                    elif lb_state and lb_state != "active":
                        evidence_gaps.append(
                            f"Application Load Balancer {lb_name} "
                            f"is not yet active (state: {lb_state})."
                        )

                    if not load_balancer.get("listeners"):
                        evidence_gaps.append(
                            f"Application Load Balancer {lb_name} "
                            "has no listeners."
                        )

                    target_groups = load_balancer.get(
                        "target_groups",
                        [],
                    )

                    if not target_groups:
                        evidence_gaps.append(
                            f"Application Load Balancer {lb_name} "
                            "has no associated target groups."
                        )

                    for target_group in target_groups:
                        checked_resources += 1

                        target_group_name = target_group.get(
                            "target_group_name",
                            "unknown",
                        )

                        targets = target_group.get("targets", [])

                        if not targets:
                            evidence_gaps.append(
                                f"Target group {target_group_name} "
                                "has no registered targets."
                            )

                        for target in targets:
                            checked_resources += 1

                            target_id = target.get(
                                "target_id",
                                "unknown",
                            )
                            target_port = target.get("port")
                            target_state = target.get(
                                "state",
                                "unknown",
                            )
                            reason = target.get("reason")
                            description = target.get("description")

                            target_reference = (
                                f"{target_id}:{target_port}"
                                if target_port is not None
                                else str(target_id)
                            )

                            if target_state == "unhealthy":
                                detail = (
                                    f" Reason: {reason}."
                                    if reason
                                    else ""
                                )

                                if description:
                                    detail += f" Description: {description}."

                                observations.append(
                                    f"ALB target {target_reference} in "
                                    f"target group {target_group_name} "
                                    f"is unhealthy.{detail}"
                                )

                                possible_causes.append(
                                    f"Target group {target_group_name} "
                                    "has an unhealthy target. Investigate "
                                    "health-check path, protocol, port, "
                                    "security groups, network connectivity, "
                                    "and application availability."
                                )

                            elif target_state != "healthy":
                                evidence_gaps.append(
                                    f"ALB target {target_reference} in "
                                    f"target group {target_group_name} "
                                    f"has not reached healthy state "
                                    f"(state: {target_state})."
                                )

        # Overall diagnosis
        if observations:
            status = "issues_detected"
            conclusion = (
                "Unhealthy infrastructure signals were observed. "
                "Possible causes are investigative leads, not a confirmed root cause."
            )

        elif evidence_gaps or not checked_resources:
            status = "insufficient_evidence"
            conclusion = (
                "No unhealthy signal was confirmed, but the available "
                "infrastructure evidence is incomplete."
            )

        else:
            status = "healthy"
            conclusion = (
                "No unhealthy EC2, Kubernetes Pod, or ALB target signals "
                "were found in the inspected resources at check time."
            )

        return {
            "status": status,
            "conclusion": conclusion,
            "checked_resource_count": checked_resources,
            "observations": observations,
            "possible_causes": list(dict.fromkeys(possible_causes)),
            "evidence_gaps": list(dict.fromkeys(evidence_gaps)),
        }

    # Retained for existing ALB and CloudWatch findings analysis.
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
                    if target.get("state") == "unhealthy":
                        evidence_available = True

                        observations.append(
                            f"Target {target.get('target_id')} in "
                            f"{group.get('target_group_name')} is unhealthy. "
                            f"Reason: {target.get('reason') or 'Not provided'}."
                        )

                        likely_causes.append(
                            "One or more ALB targets are unhealthy. "
                            "Investigate health checks, target ports, "
                            "security groups and application availability."
                        )

            for entry in item.get("cloudwatch_alb_metrics", []):
                metrics = entry.get("metrics", {})

                for metric_name in (
                    "HTTPCode_ELB_5XX_Count",
                    "HTTPCode_Target_5XX_Count",
                ):
                    total = self._total(metrics.get(metric_name, {}))

                    if total is not None:
                        evidence_available = True

                    if total is not None and total > 0:
                        observations.append(
                            f"{metric_name}: {total} errors during "
                            "the available CloudWatch observation period."
                        )

                        likely_causes.append(
                            f"{metric_name} is greater than zero. "
                            "Investigate load balancer or backend target errors."
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
                        "Unhealthy targets may contribute to request failures."
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

                for metric_name in (
                    "StatusCheckFailed",
                    "StatusCheckFailed_Instance",
                    "StatusCheckFailed_System",
                ):
                    maximum = self._maximum(
                        metrics.get(metric_name, {})
                    )

                    if maximum is not None:
                        evidence_available = True

                    if maximum is not None and maximum > 0:
                        observations.append(
                            f"EC2 {instance_id}: {metric_name} "
                            f"reached {maximum}."
                        )

                        likely_causes.append(
                            f"EC2 instance {instance_id} has a failed "
                            "status check."
                        )

                cpu = self._maximum(
                    metrics.get("CPUUtilization", {})
                )

                if cpu is not None:
                    evidence_available = True

                if cpu is not None and cpu >= 80:
                    observations.append(
                        f"EC2 {instance_id}: CPU utilization reached {cpu}%."
                    )

                    likely_causes.append(
                        f"EC2 instance {instance_id} has high CPU utilization."
                    )

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
                "These are evidence-based indicators, not a confirmed root cause."
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
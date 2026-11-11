
class DevOpsAnalyzer:

    @staticmethod
    def _extract_metric_values(
        metric_data: dict,
        statistic: str,
        metric_label: str,
        evidence_gaps: list[str],
    ) -> list[float]:
        if not isinstance(metric_data, dict):
            evidence_gaps.append(
                f"CloudWatch metric {metric_label} was not returned."
            )
            return []

        status_code = metric_data.get("status_code")

        if status_code and status_code != "Complete":
            evidence_gaps.append(
                f"CloudWatch metric {metric_label} returned "
                f"status {status_code}."
            )

        datapoints = metric_data.get("datapoints", [])

        values = [
            point[statistic]
            for point in datapoints
            if point.get(statistic) is not None
        ]

        if not values:
            evidence_gaps.append(
                f"No CloudWatch datapoints were available for {metric_label}."
            )

        return values

    def _analyze_cloudwatch_alarms(
        self,
        alarms: list[dict] | None,
        observations: list[str],
        possible_causes: list[str],
        evidence_gaps: list[str],
    ) -> None:
        for alarm in alarms or []:
            alarm_name = alarm.get("alarm_name") or "unnamed alarm"
            state = alarm.get("state_value")
            state_reason = alarm.get("state_reason")
            metric_name = alarm.get("metric_name")
            threshold = alarm.get("threshold")
            comparison = alarm.get("comparison_operator")

            dimensions = alarm.get("dimensions", [])

            dimension_summary = ", ".join(
                f"{item.get('name')}={item.get('value')}"
                for item in dimensions
                if item.get("name") and item.get("value")
            )

            details = []

            if metric_name:
                details.append(f"Metric: {metric_name}")

            if comparison and threshold is not None:
                details.append(
                    f"Condition: {comparison} {threshold}"
                )

            if dimension_summary:
                details.append(
                    f"Resource dimensions: {dimension_summary}"
                )

            detail_text = (
                " " + "; ".join(details) + "."
                if details
                else ""
            )

            if state == "ALARM":
                reason_text = (
                    f" AWS reason: {state_reason}."
                    if state_reason
                    else ""
                )

                observations.append(
                    f"CloudWatch alarm {alarm_name} is in ALARM state."
                    f"{detail_text}{reason_text}"
                )

                possible_causes.append(
                    f"CloudWatch alarm {alarm_name} entered ALARM state. "
                    "Inspect its underlying metric, affected resource, "
                    "recent metric datapoints, and related application "
                    "or infrastructure events. The alarm alone does not "
                    "confirm the root cause."
                )

            elif state == "INSUFFICIENT_DATA":
                evidence_gaps.append(
                    f"CloudWatch alarm {alarm_name} is in "
                    "INSUFFICIENT_DATA state."
                    f"{detail_text}"
                )

            elif state == "OK":
                continue

            else:
                evidence_gaps.append(
                    f"CloudWatch alarm {alarm_name} returned "
                    f"an unknown or missing state: {state or 'unknown'}."
                )

    def analyze_runtime_health(
        self,
        *,
        instances: list[dict] | None = None,
        pods: list[dict] | None = None,
        cloudwatch_metrics: list[dict] | None = None,
        alb_health: dict | None = None,
        cloudwatch_alb_metrics: list[dict] | None = None,
        cloudwatch_alarms: list[dict] | None = None,
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
            item_status = item.get("status")

            if item_status not in {"completed", "partial"}:
                evidence_gaps.append(
                    f"CloudWatch metrics unavailable for EC2 {instance_id}."
                )
                continue

            if item_status == "partial":
                evidence_gaps.append(
                    f"CloudWatch EC2 metrics are partially available "
                    f"for {instance_id}."
                )

            metrics = item.get("metrics", {})
            instance_values = {}

            metric_definitions = [
                ("CPUUtilization", "maximum"),
                ("StatusCheckFailed", "maximum"),
                ("StatusCheckFailed_Instance", "maximum"),
                ("StatusCheckFailed_System", "maximum"),
            ]

            for metric_name, statistic in metric_definitions:
                instance_values[metric_name] = (
                    self._extract_metric_values(
                        metric_data=metrics.get(metric_name, {}),
                        statistic=statistic,
                        metric_label=f"EC2 {instance_id} {metric_name}",
                        evidence_gaps=evidence_gaps,
                    )
                )

            cpu_values = instance_values["CPUUtilization"]

            if cpu_values and max(cpu_values) >= 80:
                observations.append(
                    f"EC2 {instance_id} CPU utilization "
                    f"reached {max(cpu_values)}%."
                )

                possible_causes.append(
                    f"EC2 instance {instance_id} has high CPU utilization. "
                    "Investigate workload and application resource consumption."
                )

            for metric_name in (
                "StatusCheckFailed",
                "StatusCheckFailed_Instance",
                "StatusCheckFailed_System",
            ):
                values = instance_values[metric_name]

                if values and max(values) > 0:
                    observations.append(
                        f"EC2 {instance_id}: {metric_name} "
                        f"reached {max(values)}."
                    )

                    possible_causes.append(
                        f"EC2 instance {instance_id} reported {metric_name}. "
                        "Investigate EC2 status-check details."
                    )

        # Application Load Balancer discovery and target health
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

                    lb_name = load_balancer.get("name", "unknown")
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

                            target_id = target.get("target_id", "unknown")
                            target_port = target.get("port")
                            target_state = target.get("state", "unknown")
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

        # CloudWatch Application Load Balancer metrics
        for item in cloudwatch_alb_metrics or []:
            lb_name = item.get("load_balancer_name", "unknown")
            item_status = item.get("status")

            if item_status not in {"completed", "partial"}:
                evidence_gaps.append(
                    f"CloudWatch ALB metrics unavailable for {lb_name}."
                )
                continue

            if item_status == "partial":
                evidence_gaps.append(
                    f"CloudWatch ALB metrics are partially available "
                    f"for {lb_name}."
                )

            lb_metrics = item.get("load_balancer_metrics", {})

            elb_5xx = self._extract_metric_values(
                metric_data=lb_metrics.get(
                    "HTTPCode_ELB_5XX_Count",
                    {},
                ),
                statistic="sum",
                metric_label=f"ALB {lb_name} HTTPCode_ELB_5XX_Count",
                evidence_gaps=evidence_gaps,
            )

            if elb_5xx and sum(elb_5xx) > 0:
                total_errors = sum(elb_5xx)

                observations.append(
                    f"ALB {lb_name} generated {total_errors} "
                    "HTTP 5XX errors during the observation period."
                )

                possible_causes.append(
                    f"ALB {lb_name} reported load-balancer-generated "
                    "5XX errors. Investigate listener rules, load-balancer "
                    "capacity, and backend connectivity."
                )

            for target_group in item.get(
                "target_group_metrics",
                [],
            ):
                target_group_name = target_group.get(
                    "target_group_name",
                    "unknown",
                )
                metrics = target_group.get("metrics", {})

                target_5xx = self._extract_metric_values(
                    metric_data=metrics.get(
                        "HTTPCode_Target_5XX_Count",
                        {},
                    ),
                    statistic="sum",
                    metric_label=(
                        f"Target group {target_group_name} "
                        "HTTPCode_Target_5XX_Count"
                    ),
                    evidence_gaps=evidence_gaps,
                )

                if target_5xx and sum(target_5xx) > 0:
                    observations.append(
                        f"Target group {target_group_name} generated "
                        f"{sum(target_5xx)} backend HTTP 5XX errors."
                    )

                    possible_causes.append(
                        f"Target group {target_group_name} reported "
                        "backend 5XX errors. Investigate application logs, "
                        "dependencies, and backend request handling."
                    )

                response_times = self._extract_metric_values(
                    metric_data=metrics.get(
                        "TargetResponseTime",
                        {},
                    ),
                    statistic="average",
                    metric_label=(
                        f"Target group {target_group_name} TargetResponseTime"
                    ),
                    evidence_gaps=evidence_gaps,
                )

                if response_times and max(response_times) > 1:
                    observations.append(
                        f"Target group {target_group_name} average "
                        f"response time reached {max(response_times)} seconds."
                    )

                    possible_causes.append(
                        f"Target group {target_group_name} has elevated "
                        "backend response latency. Investigate application "
                        "performance and downstream dependencies."
                    )

                healthy_hosts = self._extract_metric_values(
                    metric_data=metrics.get(
                        "HealthyHostCount",
                        {},
                    ),
                    statistic="minimum",
                    metric_label=(
                        f"Target group {target_group_name} HealthyHostCount"
                    ),
                    evidence_gaps=evidence_gaps,
                )

                if healthy_hosts and min(healthy_hosts) == 0:
                    observations.append(
                        f"Target group {target_group_name} had zero "
                        "healthy targets during the observation period."
                    )

                    possible_causes.append(
                        f"Target group {target_group_name} had no healthy "
                        "targets at one or more measurement intervals."
                    )

                unhealthy_hosts = self._extract_metric_values(
                    metric_data=metrics.get(
                        "UnHealthyHostCount",
                        {},
                    ),
                    statistic="maximum",
                    metric_label=(
                        f"Target group {target_group_name} UnHealthyHostCount"
                    ),
                    evidence_gaps=evidence_gaps,
                )

                if unhealthy_hosts and max(unhealthy_hosts) > 0:
                    observations.append(
                        f"Target group {target_group_name} unhealthy "
                        f"host count reached {max(unhealthy_hosts)}."
                    )

                    possible_causes.append(
                        f"Target group {target_group_name} has unhealthy "
                        "targets. Review target-health reasons and health checks."
                    )

        # CloudWatch alarm states
        self._analyze_cloudwatch_alarms(
            alarms=cloudwatch_alarms,
            observations=observations,
            possible_causes=possible_causes,
            evidence_gaps=evidence_gaps,
        )

        evidence_gaps = list(dict.fromkeys(evidence_gaps))
        possible_causes = list(dict.fromkeys(possible_causes))

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
                "No unhealthy EC2, Kubernetes Pod, ALB target, "
                "CloudWatch metric, or alarm signals were found "
                "in the inspected resources at check time."
            )

        return {
            "status": status,
            "conclusion": conclusion,
            "checked_resource_count": checked_resources,
            "observations": observations,
            "possible_causes": possible_causes,
            "evidence_gaps": evidence_gaps,
        }

    # Retained for existing findings analysis.
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

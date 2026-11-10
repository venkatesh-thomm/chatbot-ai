import boto3
from botocore.exceptions import BotoCoreError, ClientError


class ALBTool:
    def __init__(self, region: str | None = None):
        self.region = region
        self.elbv2 = boto3.client(
            "elbv2",
            region_name=region,
        )

    def _paginate(
        self,
        operation: str,
        result_key: str,
        **kwargs,
    ) -> list[dict]:
        items = []
        marker = None
        seen_markers = set()

        while True:
            request = dict(kwargs)

            if marker:
                request["Marker"] = marker

            response = getattr(self.elbv2, operation)(**request)
            items.extend(response.get(result_key, []))

            next_marker = response.get("NextMarker")

            if not next_marker:
                break

            if next_marker in seen_markers:
                raise RuntimeError(
                    f"Repeated pagination marker from {operation}."
                )

            seen_markers.add(next_marker)
            marker = next_marker

        return items

    def list_load_balancers(self) -> dict:
        try:
            load_balancers = self._paginate(
                "describe_load_balancers",
                "LoadBalancers",
            )

            return {
                "load_balancers": load_balancers,
            }

        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"ALB describe_load_balancers failed: {exc}"
            ) from exc

    def get_targets(self, target_group_arn: str) -> dict:
        try:
            response = self.elbv2.describe_target_health(
                TargetGroupArn=target_group_arn,
            )

            return {
                "targets": response.get(
                    "TargetHealthDescriptions",
                    [],
                )
            }

        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"ALB target health retrieval failed: {exc}"
            ) from exc

    @staticmethod
    def _normalize_listener(listener: dict) -> dict:
        default_actions = []

        for action in listener.get("DefaultActions", []):
            forward_config = action.get("ForwardConfig") or {}

            target_groups = [
                {
                    "target_group_arn": item.get("TargetGroupArn"),
                    "weight": item.get("Weight"),
                }
                for item in forward_config.get("TargetGroups", [])
            ]

            direct_target_group = action.get("TargetGroupArn")

            if direct_target_group and not target_groups:
                target_groups.append({
                    "target_group_arn": direct_target_group,
                    "weight": None,
                })

            default_actions.append({
                "type": action.get("Type"),
                "target_groups": target_groups,
            })

        return {
            "port": listener.get("Port"),
            "protocol": listener.get("Protocol"),
            "default_actions": default_actions,
        }

    def _inspect_target_group(self, target_group: dict) -> dict:
        target_group_arn = target_group["TargetGroupArn"]

        response = self.elbv2.describe_target_health(
            TargetGroupArn=target_group_arn,
        )

        targets = []
        health_counts = {}

        for description in response.get(
            "TargetHealthDescriptions",
            [],
        ):
            target = description.get("Target", {})
            health = description.get("TargetHealth", {})

            state = health.get("State", "unknown")

            health_counts[state] = health_counts.get(state, 0) + 1

            targets.append({
                "target_id": target.get("Id"),
                "port": target.get("Port"),
                "availability_zone": target.get("AvailabilityZone"),
                "state": state,
                "reason": health.get("Reason"),
                "description": health.get("Description"),
            })

        matcher = target_group.get("Matcher") or {}

        return {
            "target_group_arn": target_group_arn,
            "target_group_name": target_group.get("TargetGroupName"),
            "protocol": target_group.get("Protocol"),
            "port": target_group.get("Port"),
            "target_type": target_group.get("TargetType"),
            "health_check_enabled": target_group.get(
                "HealthCheckEnabled"
            ),
            "health_check_protocol": target_group.get(
                "HealthCheckProtocol"
            ),
            "health_check_port": target_group.get(
                "HealthCheckPort"
            ),
            "health_check_path": target_group.get(
                "HealthCheckPath"
            ),
            "health_check_interval_seconds": target_group.get(
                "HealthCheckIntervalSeconds"
            ),
            "health_check_timeout_seconds": target_group.get(
                "HealthCheckTimeoutSeconds"
            ),
            "healthy_threshold_count": target_group.get(
                "HealthyThresholdCount"
            ),
            "unhealthy_threshold_count": target_group.get(
                "UnhealthyThresholdCount"
            ),
            "matcher": {
                "http_code": matcher.get("HttpCode"),
                "grpc_code": matcher.get("GrpcCode"),
            },
            "target_count": len(targets),
            "health_counts": health_counts,
            "targets": targets,
        }

    def inspect_load_balancers(self) -> dict:
        try:
            all_load_balancers = self._paginate(
                "describe_load_balancers",
                "LoadBalancers",
            )

            application_load_balancers = [
                item
                for item in all_load_balancers
                if item.get("Type") == "application"
            ]

            results = []

            for load_balancer in application_load_balancers:
                load_balancer_arn = load_balancer["LoadBalancerArn"]

                listeners = self._paginate(
                    "describe_listeners",
                    "Listeners",
                    LoadBalancerArn=load_balancer_arn,
                )

                target_groups = self._paginate(
                    "describe_target_groups",
                    "TargetGroups",
                    LoadBalancerArn=load_balancer_arn,
                )

                state = load_balancer.get("State") or {}

                availability_zones = [
                    {
                        "zone_name": item.get("ZoneName"),
                        "subnet_id": item.get("SubnetId"),
                    }
                    for item in load_balancer.get(
                        "AvailabilityZones",
                        [],
                    )
                ]

                inspected_target_groups = [
                    self._inspect_target_group(target_group)
                    for target_group in target_groups
                ]

                results.append({
                    "load_balancer_arn": load_balancer_arn,
                    "name": load_balancer.get("LoadBalancerName"),
                    "dns_name": load_balancer.get("DNSName"),
                    "scheme": load_balancer.get("Scheme"),
                    "state": state.get("Code"),
                    "state_reason": state.get("Reason"),
                    "vpc_id": load_balancer.get("VpcId"),
                    "type": load_balancer.get("Type"),
                    "ip_address_type": load_balancer.get(
                        "IpAddressType"
                    ),
                    "security_groups": load_balancer.get(
                        "SecurityGroups",
                        [],
                    ),
                    "availability_zones": availability_zones,
                    "listener_count": len(listeners),
                    "listeners": [
                        self._normalize_listener(listener)
                        for listener in listeners
                    ],
                    "target_group_count": len(target_groups),
                    "target_groups": inspected_target_groups,
                })

            return {
                "load_balancer_count": len(results),
                "load_balancers": results,
            }

        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(
                f"ALB investigation failed: {exc}"
            ) from exc
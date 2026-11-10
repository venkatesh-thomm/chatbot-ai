import os


class KubernetesToolError(RuntimeError):
    """Raised when Kubernetes pod status cannot be read."""


class KubernetesTool:
    """Read pod health from one configured Kubernetes namespace."""

    def __init__(self, namespace: str, core_v1_api=None):
        self.namespace = namespace

        # Import lazily so deployments that do not enable Kubernetes need not
        # initialize Kubernetes client configuration during application startup.
        try:
            from kubernetes import client, config
            from kubernetes.client.exceptions import ApiException
            from kubernetes.config.config_exception import ConfigException
        except ImportError as exc:
            raise KubernetesToolError(
                "Install the kubernetes Python package to enable pod inspection."
            ) from exc

        self.api_exception = ApiException
        if core_v1_api is not None:
            self.core_v1_api = core_v1_api
            return

        try:
            if os.getenv("KUBERNETES_SERVICE_HOST"):
                config.load_incluster_config()
            else:
                config.load_kube_config()
            self.core_v1_api = client.CoreV1Api()
        except ConfigException as exc:
            raise KubernetesToolError(
                "Kubernetes client configuration is not available."
            ) from exc

    def list_pods(self) -> dict:
        try:
            response = self.core_v1_api.list_namespaced_pod(
                namespace=self.namespace,
            )
        except self.api_exception as exc:
            # Do not expose raw API bodies or credentials in the public response.
            raise KubernetesToolError(
                f"Kubernetes pod listing failed with HTTP {exc.status}."
            ) from exc

        pods = [self._pod_summary(pod) for pod in response.items]
        warning_events = self._warning_events()
        events_by_pod = {}
        for event in warning_events:
            events_by_pod.setdefault(event["pod_name"], []).append(event)

        for pod in pods:
            pod["warning_events"] = events_by_pod.get(pod["name"], [])[:3]

        return {
            "namespace": self.namespace,
            "pods": pods,
            "pod_count": len(pods),
            "unhealthy_pod_count": sum(not pod["ready"] for pod in pods),
        }

    def _warning_events(self) -> list[dict]:
        try:
            response = self.core_v1_api.list_namespaced_event(
                namespace=self.namespace,
                field_selector="type=Warning",
            )
        except self.api_exception as exc:
            raise KubernetesToolError(
                f"Kubernetes warning event lookup failed with HTTP {exc.status}."
            ) from exc

        events = []
        for event in response.items:
            involved_object = getattr(event, "involved_object", None)
            if (
                not involved_object
                or involved_object.kind != "Pod"
                or not involved_object.name
            ):
                continue
            events.append(
                {
                    "pod_name": involved_object.name,
                    "reason": event.reason,
                    "message": event.message,
                    "count": event.count,
                    "last_seen": self._timestamp(
                        getattr(event, "last_timestamp", None)
                        or getattr(event, "event_time", None)
                    ),
                }
            )
        events.sort(key=lambda event: event["last_seen"] or "", reverse=True)
        return events

    @staticmethod
    def _timestamp(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    @staticmethod
    def _pod_summary(pod) -> dict:
        status = pod.status
        container_statuses = (status.container_statuses or []) if status else []
        container_summaries = []

        for container in container_statuses:
            state = container.state
            waiting = getattr(state, "waiting", None)
            terminated = getattr(state, "terminated", None)
            container_summaries.append(
                {
                    "name": container.name,
                    "ready": container.ready,
                    "restart_count": container.restart_count,
                    "state": (
                        "waiting"
                        if waiting
                        else "terminated"
                        if terminated
                        else "running"
                        if getattr(state, "running", None)
                        else "unknown"
                    ),
                    "reason": (
                        waiting.reason
                        if waiting
                        else terminated.reason
                        if terminated
                        else None
                    ),
                }
            )

        ready = bool(container_statuses) and all(
            container.ready for container in container_statuses
        )
        return {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "phase": status.phase if status and status.phase else "Unknown",
            "ready": ready,
            "node": pod.spec.node_name,
            "pod_ip": status.pod_ip if status else None,
            "restart_count": sum(
                container.restart_count for container in container_statuses
            ),
            "containers": container_summaries,
        }

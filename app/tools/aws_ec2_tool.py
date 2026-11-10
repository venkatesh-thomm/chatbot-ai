import boto3
from botocore.exceptions import ClientError


class EC2Tool:
    def __init__(self, region: str | None = None):
        self.region = region
        self.client = boto3.client("ec2", region_name=region)

    def list_instances(
        self,
        *,
        tag_key: str | None = None,
        tag_value: str | None = None,
    ):
        if bool(tag_key) != bool(tag_value):
            raise ValueError("tag_key and tag_value must be provided together.")

        paginator_args = {}
        if tag_key and tag_value:
            paginator_args["Filters"] = [
                {"Name": f"tag:{tag_key}", "Values": [tag_value]}
            ]
        try:
            instances = []
            paginator = self.client.get_paginator("describe_instances")
            for page in paginator.paginate(**paginator_args):
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        instances.append(
                            {
                                "instance_id": instance["InstanceId"],
                                "state": instance["State"]["Name"],
                                "state_reason": (
                                    instance.get("StateReason") or {}
                                ).get("Message"),
                                "instance_type": instance.get("InstanceType"),
                                "public_ip": instance.get("PublicIpAddress"),
                                "private_ip": instance.get("PrivateIpAddress"),
                                "tags": {
                                    tag["Key"]: tag["Value"]
                                    for tag in instance.get("Tags", [])
                                },
                            }
                        )
            status_by_id = self._instance_statuses(
                [instance["instance_id"] for instance in instances]
            )
            for instance in instances:
                instance["status_checks"] = status_by_id.get(
                    instance["instance_id"]
                )
            return {"instances": instances}
        except ClientError as exc:
            raise RuntimeError(f"EC2 describe_instances failed: {exc}") from exc

    def _instance_statuses(self, instance_ids: list[str]) -> dict:
        statuses = {}
        try:
            for offset in range(0, len(instance_ids), 100):
                response = self.client.describe_instance_status(
                    InstanceIds=instance_ids[offset : offset + 100],
                    IncludeAllInstances=True,
                )
                for item in response.get("InstanceStatuses", []):
                    statuses[item["InstanceId"]] = {
                        "instance_status": item.get("InstanceStatus", {}).get(
                            "Status", "unknown"
                        ),
                        "system_status": item.get("SystemStatus", {}).get(
                            "Status", "unknown"
                        ),
                        "events": [
                            {
                                "code": event.get("Code"),
                                "description": event.get("Description"),
                                "not_before": event.get("NotBefore"),
                                "not_after": event.get("NotAfter"),
                            }
                            for event in item.get("Events", [])
                        ],
                    }
        except ClientError as exc:
            raise RuntimeError(
                f"EC2 describe_instance_status failed: {exc}"
            ) from exc
        return statuses

    def get_instance(self, instance_id: str) -> dict | None:
        try:
            response = self.client.describe_instances(InstanceIds=[instance_id])
            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    result = {
                        "instance_id": instance["InstanceId"],
                        "state": instance["State"]["Name"],
                        "state_reason": (
                            instance.get("StateReason") or {}
                        ).get("Message"),
                        "tags": {
                            tag["Key"]: tag["Value"]
                            for tag in instance.get("Tags", [])
                        },
                    }
                    result["status_checks"] = self._instance_statuses(
                        [instance_id]
                    ).get(instance_id)
                    return result
            return None
        except ClientError as exc:
            raise RuntimeError(f"EC2 describe_instance failed: {exc}") from exc

    def stop_instance(self, instance_id: str):
        try:
            self.client.stop_instances(InstanceIds=[instance_id])
            return {"status": "stopping", "instance_id": instance_id}
        except ClientError as exc:
            raise RuntimeError(f"EC2 stop failed: {exc}") from exc

    def start_instance(self, instance_id: str):
        try:
            self.client.start_instances(InstanceIds=[instance_id])
            return {"status": "starting", "instance_id": instance_id}
        except ClientError as exc:
            raise RuntimeError(f"EC2 start failed: {exc}") from exc

    def reboot_instance(self, instance_id: str):
        try:
            self.client.reboot_instances(InstanceIds=[instance_id])
            return {"status": "rebooting", "instance_id": instance_id}
        except ClientError as exc:
            raise RuntimeError(f"EC2 reboot failed: {exc}") from exc
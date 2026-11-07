import re
import boto3

from app.config import get_settings


class AWSEC2ReadOnlyTool:

    def __init__(self, client=None):
        settings = get_settings()
        self.region = settings.aws_region

        self.client = client or boto3.client(
            "ec2",
            region_name=self.region,
        )

    def inspect_instances(self, request: str) -> dict:

        match = re.search(
            r"\bi-[0-9a-fA-F]{8,17}\b",
            request,
        )

        instance_id = match.group(0) if match else None

        params = {}

        if instance_id:
            params["InstanceIds"] = [instance_id]
        else:
            params["Filters"] = [
                {
                    "Name": "instance-state-name",
                    "Values": [
                        "pending",
                        "running",
                        "stopping",
                        "stopped",
                    ],
                }
            ]

        paginator = self.client.get_paginator(
            "describe_instances"
        )

        instance_records = []

        pages = paginator.paginate(
            **params,
            PaginationConfig={
                "MaxItems": 100,
                "PageSize": 100,
            },
        )

        for page in pages:
            for reservation in page.get("Reservations", []):
                for instance in reservation.get("Instances", []):

                    tags = {
                        tag["Key"]: tag["Value"]
                        for tag in instance.get("Tags", [])
                    }

                    launch_time = instance.get("LaunchTime")

                    instance_records.append({
                        "instance_id": instance.get("InstanceId"),
                        "name": tags.get("Name"),
                        "instance_type": instance.get("InstanceType"),
                        "state": instance.get("State", {}).get("Name"),
                        "availability_zone": instance.get(
                            "Placement", {}
                        ).get("AvailabilityZone"),
                        "vpc_id": instance.get("VpcId"),
                        "subnet_id": instance.get("SubnetId"),
                        "private_ip": instance.get("PrivateIpAddress"),
                        "security_groups": [
                            group.get("GroupId")
                            for group in instance.get("SecurityGroups", [])
                        ],
                        "launch_time": (
                            launch_time.isoformat()
                            if launch_time else None
                        ),
                    })

        instance_ids = [
            item["instance_id"]
            for item in instance_records
        ]

        status_map = {}

        if instance_ids:
            status_paginator = self.client.get_paginator(
                "describe_instance_status"
            )

            status_pages = status_paginator.paginate(
                InstanceIds=instance_ids,
                IncludeAllInstances=True,
                PaginationConfig={
                    "MaxItems": 100,
                    "PageSize": 100,
                },
            )

            for page in status_pages:
                for status in page.get("InstanceStatuses", []):

                    status_map[status["InstanceId"]] = {
                        "instance_status": status.get(
                            "InstanceStatus", {}
                        ).get("Status", "not_reported"),

                        "system_status": status.get(
                            "SystemStatus", {}
                        ).get("Status", "not_reported"),

                        "availability_zone": status.get(
                            "AvailabilityZone"
                        ),

                        "events": [
                            {
                                "code": event.get("Code"),
                                "description": event.get("Description"),
                            }
                            for event in status.get("Events", [])
                        ],
                    }

        for instance in instance_records:
            instance["status_checks"] = status_map.get(
                instance["instance_id"],
                {
                    "instance_status": "not_reported",
                    "system_status": "not_reported",
                    "events": [],
                },
            )

        return {
            "tool": "aws_ec2_read_only",
            "region": self.region,
            "instance_count": len(instance_records),
            "instances": instance_records,
            "scope": (
                f"Instance {instance_id}"
                if instance_id else "Non-terminated EC2 instances"
            ),
        }


import subprocess
import sys

REGION = "us-east-1"
CLUSTER = "enterprise-rag-dev"
ECR_REPO = "enterprise-rag-dev-api"
TF_DIR = "infrastructure/terraform"


def run(command, cwd=None, capture=False):
    print(f"\n>>> {' '.join(command)}")

    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=capture
    )

    if capture and result.stdout:
        print(result.stdout)

    if result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr)
        raise RuntimeError("Command failed.")

    return result.stdout if capture else None


def main():
    print("Starting DevOps AI Agent infrastructure deployment")

    # 1. Check tools
    for tool in ["aws", "terraform", "kubectl", "helm"]:
        run([tool, "--version"])

    # 2. Verify AWS identity
    run(["aws", "sts", "get-caller-identity"])

    # 3. Update Helm repositories
    run(["helm", "repo", "update"])

    # 4. Terraform initialization
    run(["terraform", "init"], cwd=TF_DIR)

    # 5. Format and validate
    run(["terraform", "fmt", "-recursive"], cwd=TF_DIR)
    run(["terraform", "validate"], cwd=TF_DIR)

    # 6. Check ECR repository
    result = subprocess.run(
        [
            "aws", "ecr", "describe-repositories",
            "--repository-names", ECR_REPO,
            "--region", REGION
        ],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        state = subprocess.run(
            ["terraform", "state", "show",
             "aws_ecr_repository.api"],
            cwd=TF_DIR,
            capture_output=True,
            text=True
        )

        if state.returncode != 0:
            print("Importing existing ECR repository...")
            run([
                "terraform", "import",
                "aws_ecr_repository.api",
                ECR_REPO
            ], cwd=TF_DIR)
        else:
            print("ECR already managed by Terraform.")

    # 7. Verify EKS status
    status = run([
        "aws", "eks", "describe-cluster",
        "--name", CLUSTER,
        "--region", REGION,
        "--query", "cluster.status",
        "--output", "text"
    ], capture=True).strip()

    if status != "ACTIVE":
        raise RuntimeError(f"EKS cluster status: {status}")

    # 8. Configure Kubernetes
    run([
        "aws", "eks", "update-kubeconfig",
        "--region", REGION,
        "--name", CLUSTER
    ])

    run(["kubectl", "cluster-info"])
    run(["kubectl", "get", "nodes"])

    # 9. Create Terraform plan
    run([
        "terraform", "plan",
        "-out=tfplan"
    ], cwd=TF_DIR)

    # 10. Confirmation
    confirm = input(
        "\nReview the plan. Proceed with apply? (yes/no): "
    )

    if confirm.strip().lower() != "yes":
        print("Deployment cancelled.")
        return

    # 11. Apply
    run([
        "terraform", "apply", "tfplan"
    ], cwd=TF_DIR)

    print("\nInfrastructure deployment completed!")

    run(["kubectl", "get", "nodes"])
    run(["kubectl", "get", "pods", "-A"])


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as error:
        print(f"\nDEPLOYMENT FAILED: {error}")
        sys.exit(1)

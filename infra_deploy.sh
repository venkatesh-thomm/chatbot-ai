#!/bin/bash
set -Eeuo pipefail

# ==========================================
# DevOps AI Agent - Full Deployment
# ==========================================

REGION="us-east-1"
CLUSTER_NAME="enterprise-rag-dev"

ACCOUNT_ID="210006515453"
ECR_REPOSITORY="enterprise-rag-dev-api"

LOCAL_IMAGE="enterprise-rag-fastapi"
IMAGE_TAG="phase1"

TF_DIR="infrastructure/terraform"
TF_VARS="terraform.tfvars"

ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
REMOTE_IMAGE="${ECR_URI}/${ECR_REPOSITORY}:${IMAGE_TAG}"

echo "=========================================="
echo " DevOps AI Agent Deployment Started"
echo "=========================================="

# ------------------------------------------
# STEP 1: Check required tools
# ------------------------------------------

echo "[1/10] Checking required tools..."

for tool in aws terraform kubectl helm docker; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "ERROR: $tool is not installed."
        exit 1
    }
done

if [ ! -f "Dockerfile" ]; then
    echo "ERROR: Dockerfile not found."
    exit 1
fi

if [ ! -f "$TF_DIR/$TF_VARS" ]; then
    echo "ERROR: terraform.tfvars not found."
    exit 1
fi

docker info >/dev/null 2>&1 || {
    echo "ERROR: Docker daemon is not running."
    exit 1
}

# ------------------------------------------
# STEP 2: Verify AWS identity and ECR
# ------------------------------------------

echo "[2/10] Verifying AWS credentials..."

aws sts get-caller-identity

CURRENT_ACCOUNT=$(aws sts get-caller-identity \
    --query Account --output text)

if [ "$CURRENT_ACCOUNT" != "$ACCOUNT_ID" ]; then
    echo "ERROR: AWS account mismatch!"
    exit 1
fi

echo "Checking existing ECR repository..."

aws ecr describe-repositories \
    --repository-names "$ECR_REPOSITORY" \
    --region "$REGION" >/dev/null

# ------------------------------------------
# STEP 3: Docker build, tag and push
# ------------------------------------------

echo "[3/10] Authenticating Docker with ECR..."

aws ecr get-login-password \
    --region "$REGION" | \
docker login \
    --username AWS \
    --password-stdin "$ECR_URI"

echo "Building FastAPI Docker image..."

docker build \
    -t "${LOCAL_IMAGE}:${IMAGE_TAG}" .

echo "Tagging Docker image..."

docker tag \
    "${LOCAL_IMAGE}:${IMAGE_TAG}" \
    "$REMOTE_IMAGE"

echo "Pushing Docker image to ECR..."

docker push "$REMOTE_IMAGE"

echo "Verifying ECR image..."

aws ecr describe-images \
    --repository-name "$ECR_REPOSITORY" \
    --region "$REGION" \
    --image-ids "imageTag=${IMAGE_TAG}"

echo "Docker image successfully pushed:"
echo "$REMOTE_IMAGE"



# ------------------------------------------
# STEP 9: Update Helm repositories
# ------------------------------------------

echo "[9/10] Updating Helm repositories..."

helm repo update


# ------------------------------------------
# STEP 4: Initialize Terraform
# ------------------------------------------

echo "[4/10] Initializing Terraform..."

terraform -chdir="$TF_DIR" init

# ------------------------------------------
# STEP 5: Format and validate Terraform
# ------------------------------------------

echo "[5/10] Formatting and validating Terraform..."

terraform -chdir="$TF_DIR" fmt -recursive

terraform -chdir="$TF_DIR" validate

# ------------------------------------------
# STEP 6: Import existing ECR if necessary
# ------------------------------------------

echo "[6/10] Checking Terraform ECR state..."

if ! terraform -chdir="$TF_DIR" state show \
    aws_ecr_repository.api >/dev/null 2>&1; then

    echo "Importing existing ECR repository..."

    terraform -chdir="$TF_DIR" import \
        -var-file="$TF_VARS" \
        aws_ecr_repository.api "$ECR_REPOSITORY"
else
    echo "ECR repository already managed by Terraform."
fi

# ------------------------------------------
# STEP 7: Apply ONLY ECR
# ------------------------------------------

echo "[7/10] Applying ECR repository only..."

terraform -chdir="$TF_DIR" plan \
    -var-file="$TF_VARS" \
    -target=aws_ecr_repository.api \
    -out=ecr.tfplan

terraform -chdir="$TF_DIR" apply ecr.tfplan

# ------------------------------------------
# STEP 8: Verify EKS connectivity
# ------------------------------------------

echo "[8/10] Checking EKS cluster..."

CLUSTER_STATUS=$(aws eks describe-cluster \
    --name "$CLUSTER_NAME" \
    --region "$REGION" \
    --query "cluster.status" \
    --output text)

echo "EKS Status: $CLUSTER_STATUS"

if [ "$CLUSTER_STATUS" != "ACTIVE" ]; then
    echo "ERROR: EKS cluster is not ACTIVE."
    exit 1
fi

echo "Updating kubeconfig..."

aws eks update-kubeconfig \
    --region "$REGION" \
    --name "$CLUSTER_NAME"

echo "Verifying Kubernetes connectivity..."

kubectl cluster-info
kubectl get nodes

# ------------------------------------------
# STEP 10: Full Terraform deployment
# ------------------------------------------

echo "[10/10] Creating complete Terraform plan..."

terraform -chdir="$TF_DIR" plan \
    -var-file="$TF_VARS" \
    -out=tfplan

echo ""
echo "=========================================="
echo " Review Terraform Plan"
echo "=========================================="

read -r -p "Proceed with full Terraform apply? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Deployment cancelled."
    exit 0
fi

terraform -chdir="$TF_DIR" apply tfplan

# ------------------------------------------
# FINAL VERIFICATION
# ------------------------------------------

echo ""
echo "=========================================="
echo " Deployment Completed"
echo "=========================================="

echo "Docker Image:"
echo "$REMOTE_IMAGE"

echo ""
echo "EKS Nodes:"
kubectl get nodes

echo ""
echo "Kubernetes Pods:"
kubectl get pods -A

echo ""
echo "=========================================="
echo " All Deployment Steps Completed"
echo "=========================================="
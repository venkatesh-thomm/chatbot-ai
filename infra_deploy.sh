
#!/bin/bash
set -Eeuo pipefail

# ==========================================
# DevOps AI Agent - Full Infrastructure Deployment
# Terraform + Docker + AWS ECR + EKS
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

echo "[1/12] Checking required tools..."

for tool in aws terraform kubectl helm docker; do
    command -v "$tool" >/dev/null 2>&1 || {
        echo "ERROR: $tool is not installed."
        exit 1
    }
done

# Check Terraform variables file
if [ ! -f "$TF_DIR/$TF_VARS" ]; then
    echo "ERROR: $TF_DIR/$TF_VARS not found."
    exit 1
fi

# Check Dockerfile
if [ ! -f "Dockerfile" ]; then
    echo "ERROR: Dockerfile not found in project root."
    exit 1
fi

# ------------------------------------------
# STEP 2: Verify AWS identity
# ------------------------------------------

echo "[2/12] Verifying AWS credentials..."

aws sts get-caller-identity

CURRENT_ACCOUNT=$(aws sts get-caller-identity \
    --query Account --output text)

if [ "$CURRENT_ACCOUNT" != "$ACCOUNT_ID" ]; then
    echo "ERROR: AWS account mismatch!"
    exit 1
fi

# ------------------------------------------
# STEP 3: Initialize Terraform
# ------------------------------------------

echo "[3/12] Initializing Terraform..."

terraform -chdir="$TF_DIR" init

# ------------------------------------------
# STEP 4: Format and validate Terraform
# ------------------------------------------

echo "[4/12] Formatting and validating Terraform..."

terraform -chdir="$TF_DIR" fmt -recursive

terraform -chdir="$TF_DIR" validate

# ------------------------------------------
# STEP 5: Check and import existing ECR
# ------------------------------------------

echo "[5/12] Checking ECR repository..."

if aws ecr describe-repositories \
    --repository-names "$ECR_REPOSITORY" \
    --region "$REGION" >/dev/null 2>&1; then

    if ! terraform -chdir="$TF_DIR" state show \
        aws_ecr_repository.api >/dev/null 2>&1; then

        echo "Importing existing ECR repository..."

        terraform -chdir="$TF_DIR" import \
            -var-file="$TF_VARS" \
            aws_ecr_repository.api "$ECR_REPOSITORY"
    else
        echo "ECR repository already managed by Terraform."
    fi
else
    echo "ECR repository does not exist."
    echo "Terraform will create it."
fi

# ------------------------------------------
# STEP 6: Apply ONLY ECR resource
# ------------------------------------------

echo "[6/12] Applying ECR repository only..."

terraform -chdir="$TF_DIR" plan \
    -var-file="$TF_VARS" \
    -target=aws_ecr_repository.api \
    -out=ecr.tfplan

terraform -chdir="$TF_DIR" apply ecr.tfplan

echo "ECR repository is ready."

# ------------------------------------------
# STEP 7: Authenticate Docker with ECR
# ------------------------------------------

echo "[7/12] Authenticating Docker with AWS ECR..."

aws ecr get-login-password \
    --region "$REGION" | \
docker login \
    --username AWS \
    --password-stdin "$ECR_URI"

# ------------------------------------------
# STEP 8: Build Docker image
# ------------------------------------------

echo "[8/12] Building FastAPI Docker image..."

docker build \
    -t "${LOCAL_IMAGE}:${IMAGE_TAG}" .

# ------------------------------------------
# STEP 9: Tag Docker image
# ------------------------------------------

echo "[9/12] Tagging Docker image..."

docker tag \
    "${LOCAL_IMAGE}:${IMAGE_TAG}" \
    "$REMOTE_IMAGE"

# ------------------------------------------
# STEP 10: Push Docker image to ECR
# ------------------------------------------

echo "[10/12] Pushing Docker image to ECR..."

docker push "$REMOTE_IMAGE"

echo "Verifying image in ECR..."

aws ecr describe-images \
    --repository-name "$ECR_REPOSITORY" \
    --region "$REGION" \
    --image-ids "imageTag=${IMAGE_TAG}"

# ------------------------------------------
# STEP 11: Verify EKS and Kubernetes
# ------------------------------------------

echo "[11/12] Checking EKS cluster..."

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

echo "Checking Kubernetes connectivity..."

kubectl cluster-info

kubectl get nodes

# ------------------------------------------
# STEP 12: Apply remaining infrastructure
# ------------------------------------------

echo "[12/12] Updating Helm repositories..."

helm repo update

echo "Creating complete Terraform plan..."

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

echo "Applying remaining infrastructure..."

terraform -chdir="$TF_DIR" apply tfplan

# ------------------------------------------
# FINAL VERIFICATION
# ------------------------------------------

echo ""
echo "=========================================="
echo " Deployment Completed"
echo "=========================================="

echo "Docker image:"
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

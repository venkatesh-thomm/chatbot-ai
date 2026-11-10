#!/bin/bash
set -Eeuo pipefail

# ==========================================
# DevOps AI Agent - Infrastructure Destroy
# Order: ECR Images -> Kubernetes -> Terraform
# ==========================================

REGION="us-east-1"
ACCOUNT_ID="210006515453"
CLUSTER_NAME="enterprise-rag-dev"
ECR_REPOSITORY="enterprise-rag-dev-api"

TF_DIR="infrastructure/terraform"
TF_VARS="terraform.tfvars"

echo "=========================================="
echo " Destruction Started"
echo "=========================================="

# ------------------------------------------
# STEP 1: Delete ECR Images First
# ------------------------------------------
echo "[1/3] Deleting all ECR images..."

if aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" --region "$REGION" >/dev/null 2>&1; then
    IMAGE_DIGESTS=$(aws ecr list-images --repository-name "$ECR_REPOSITORY" --region "$REGION" --query 'imageIds[*].imageDigest' --output text)

    if [[ -n "$IMAGE_DIGESTS" && "$IMAGE_DIGESTS" != "None" ]]; then
        for digest in $IMAGE_DIGESTS; do
            echo "Deleting ECR image: $digest"
            aws ecr batch-delete-image \
                --repository-name "$ECR_REPOSITORY" \
                --region "$REGION" \
                --image-ids "imageDigest=$digest" >/dev/null
        done
        echo "All ECR images deleted successfully."
    else
        echo "No ECR images found."
    fi
else
    echo "ECR repository not found. Skipping."
fi

# ------------------------------------------
# STEP 2: Delete Kubernetes Resources Second
# ------------------------------------------
echo ""
echo "[2/3] Deleting Kubernetes resources..."

if aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" >/dev/null 2>&1; then
    CLUSTER_STATUS=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --query "cluster.status" --output text)
    
    if [ "$CLUSTER_STATUS" == "ACTIVE" ]; then
        aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER_NAME"
        
        echo "Deleting Kubernetes resources..."
        kubectl delete all --all --all-namespaces --wait=true || true
        echo "Kubernetes resources deleted successfully."
    else
        echo "EKS cluster is not active ($CLUSTER_STATUS). Skipping kubectl cleanup."
    fi
else
    echo "EKS cluster not found. Skipping Kubernetes cleanup."
fi

# ------------------------------------------
# STEP 3: Run Terraform Destroy Last
# ------------------------------------------
echo ""
echo "[3/3] Running Terraform destroy..."

terraform -chdir="$TF_DIR" init

# Ensure ECR repository is in state so Terraform can destroy it cleanly
if aws ecr describe-repositories --repository-names "$ECR_REPOSITORY" --region "$REGION" >/dev/null 2>&1; then
    if ! terraform -chdir="$TF_DIR" state show aws_ecr_repository.api >/dev/null 2>&1; then
        terraform -chdir="$TF_DIR" import -var-file="$TF_VARS" aws_ecr_repository.api "$ECR_REPOSITORY" || true
    fi
fi

terraform -chdir="$TF_DIR" destroy -auto-approve -var-file="$TF_VARS"

echo ""
echo "=========================================="
echo " Infrastructure Destruction Completed Successfully!"
echo "=========================================="
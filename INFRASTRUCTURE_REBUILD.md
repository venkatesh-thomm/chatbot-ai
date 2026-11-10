# Infrastructure rebuild notes

This update reuses the existing Terraform resources and filenames. It does not introduce a second Terraform root, a new state, or a replacement architecture.

## Important configuration before provisioning

1. Open `infrastructure/terraform/terraform.tfvars`.
2. Set `eks_public_access_cidrs` to your current public IPv4 address with `/32`. Do not use `0.0.0.0/0`.
3. Confirm `s3_documents_bucket` is the existing bucket you intend the application to use. The bucket is referenced by IAM but is not created or destroyed by this Terraform stack.
4. Confirm `terraform_iam_user_name` is the IAM user that should receive development ECR push and OpenSearch API permissions, or set it to `null` if those permissions are managed elsewhere.

## Why provisioning is two-stage

The AWS provider can create the VPC and EKS cluster before a Kubernetes API exists. Helm and kubectl providers cannot reliably install the controller or CRDs until EKS is active and a current kubeconfig is available. Keep the same directory and state, but run the initial AWS/EKS stage first, refresh kubeconfig, then run the full apply.

Run these commands from the repository root in Git Bash:

```bash
helm repo update
terraform -chdir=infrastructure/terraform init
terraform -chdir=infrastructure/terraform fmt -recursive
terraform -chdir=infrastructure/terraform validate

terraform -chdir=infrastructure/terraform apply \
  -target=aws_eks_node_group.main \
  -target=aws_eks_addon.coredns \
  -target=aws_iam_role_policy.app \
  -target=aws_iam_role_policy_attachment.lbc \
  -target=aws_opensearchserverless_access_policy.main \
  -target=aws_ecr_repository.api \
  -target=aws_wafv2_web_acl.enterprise_rag

aws eks update-kubeconfig --region us-east-1 --name enterprise-rag-dev

terraform -chdir=infrastructure/terraform apply
```

Review each plan before approving it. The first apply creates AWS-side dependencies and the EKS worker nodes. The second apply installs Gateway API CRDs, AWS Load Balancer Controller CRDs, and the Helm release in dependency order.

## Load Balancer Controller ownership

Helm now creates and owns the `aws-load-balancer-controller` ServiceAccount and annotates it with the IRSA role. Do not separately apply a second ServiceAccount manifest for that controller. The application ServiceAccount remains in `k8s/service-account.yaml` and is annotated with the FastAPI IRSA role.

## Application manifests after provisioning

The old OpenSearch endpoint and WAF ARN were tied to the destroyed stack. After Terraform completes:

- Replace `REPLACE_WITH_TERRAFORM_OPENSEARCH_COLLECTION_ENDPOINT` in `k8s/deployment.yaml` with `terraform -chdir=infrastructure/terraform output -raw opensearch_collection_endpoint`.
- Add the fresh WAF ARN from `terraform -chdir=infrastructure/terraform output -raw waf_web_acl_arn` under `wafV2.webACL` in `k8s/gateway-api.yaml`.
- Replace `REPLACE_WITH_ECR_IMAGE_URI` in `k8s/deployment.yaml` with the image URI from `terraform -chdir=infrastructure/terraform output -raw ecr_repository_url` plus the tag you build and push. Do this before applying the Deployment manifest.

## Safe destroy order

If the cluster and local kubeconfig are still available, remove Kubernetes-managed resources first, then destroy AWS infrastructure:

```bash
# First remove Gateway resources so the controller can clean up the ALB.
kubectl delete -f k8s/gateway-api.yaml --ignore-not-found

# Then remove the controller and its CRDs while EKS is still available.
terraform -chdir=infrastructure/terraform destroy \
  -target=helm_release.aws_load_balancer_controller \
  -target=kubectl_manifest.gateway_api \
  -target=kubectl_manifest.aws_lbc_gateway \
  -target=kubectl_manifest.aws_lbc_base

# Finally remove the remaining AWS resources.
terraform -chdir=infrastructure/terraform destroy
```

The first command removes Gateway resources while the controller is still running, allowing it to clean up the ALB. The targeted Terraform destroy then removes the Helm release and CRDs while the Kubernetes API is available. The final destroy removes the remaining AWS resources. If the cluster has already been deleted outside Terraform, do not run the targeted Kubernetes destroy; reconcile the Terraform state instead.

## Cost notes

The existing development design retains one NAT Gateway, two `t3.medium` EKS worker nodes (desired capacity), and an OpenSearch Serverless collection. These are billable resources. Destroy the stack when it is not needed, while remembering that the externally managed S3 bucket is not deleted by this configuration.

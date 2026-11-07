variable "aws_region" {
  description = "AWS deployment region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming and tags"
  type        = string
  default     = "enterprise-rag"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets in two AZs"
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets in two AZs"
  type        = list(string)
  default     = ["10.20.11.0/24", "10.20.12.0/24"]
}


variable "eks_cluster_name" {
  description = "EKS cluster name"
  type        = string
  default     = "enterprise-rag-dev"
}


variable "eks_cluster_version" {
  description = "Kubernetes version for EKS"
  type        = string
  default     = "1.36"
}

variable "eks_public_access_cidrs" {
  description = "Public IPv4 CIDRs allowed to access the EKS API; set your current public IP as /32"
  type        = list(string)

  validation {
    condition     = length(var.eks_public_access_cidrs) > 0 && alltrue([for cidr in var.eks_public_access_cidrs : can(cidrhost(cidr, 0))])
    error_message = "Set at least one valid CIDR, preferably your current public IP with /32. Do not use 0.0.0.0/0."
  }
}

variable "s3_documents_bucket" {
  description = "Name of the existing S3 bucket used for repository documents; this bucket is managed outside this Terraform configuration"
  type        = string
  default     = "venkatesh-dem1"
}

variable "terraform_iam_user_name" {
  description = "Existing IAM user that needs development ECR push and OpenSearch API permissions; set null if permissions are managed elsewhere"
  type        = string
  default     = "dev"
  nullable    = true
}

variable "bedrock_embedding_model_id" {
  description = "Bedrock embedding foundation model ID used by the application"
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "kubeconfig_path" {
  description = "Local kubeconfig path used by Helm and kubectl providers after EKS has been created"
  type        = string
  default     = "~/.kube/config"
}

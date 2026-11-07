provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Helm and kubectl providers require a live EKS cluster and a current kubeconfig.
# Apply the AWS/EKS foundation first, run aws eks update-kubeconfig, then run full terraform apply.
provider "helm" {
  kubernetes {
    config_path = pathexpand(var.kubeconfig_path)
  }
}

provider "kubectl" {
  config_path = pathexpand(var.kubeconfig_path)
}

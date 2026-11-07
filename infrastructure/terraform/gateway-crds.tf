# Standard Kubernetes Gateway API CRDs must exist before AWS-specific Gateway API CRDs.
data "kubectl_file_documents" "gateway_api" {
  content = file("${path.module}/gateway-api-standard-install.yaml")
}

resource "kubectl_manifest" "gateway_api" {
  for_each  = data.kubectl_file_documents.gateway_api.manifests
  yaml_body = each.value

  server_side_apply = true
}

# AWS Load Balancer Controller Gateway API CRDs.
data "kubectl_file_documents" "aws_lbc_gateway" {
  content = file("${path.module}/aws-lbc-gateway-crds.yaml")
}

resource "kubectl_manifest" "aws_lbc_gateway" {
  for_each  = data.kubectl_file_documents.aws_lbc_gateway.manifests
  yaml_body = each.value

  server_side_apply = true
  force_conflicts   = true

  depends_on = [kubectl_manifest.gateway_api]
}

# AWS Load Balancer Controller base CRDs.
data "kubectl_file_documents" "aws_lbc_base" {
  content = file("${path.module}/aws-lbc-base-crds.yaml")
}

resource "kubectl_manifest" "aws_lbc_base" {
  for_each  = data.kubectl_file_documents.aws_lbc_base.manifests
  yaml_body = each.value

  server_side_apply = true
  force_conflicts   = true

  depends_on = [kubectl_manifest.gateway_api]
}

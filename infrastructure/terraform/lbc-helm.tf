resource "helm_release" "aws_load_balancer_controller" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = "3.6.2"

  namespace        = "kube-system"
  create_namespace = false

  wait    = true
  timeout = 600

  set {
    name  = "clusterName"
    value = aws_eks_cluster.main.name
  }

  set {
    name  = "region"
    value = var.aws_region
  }

  set {
    name  = "vpcId"
    value = aws_vpc.main.id
  }

  # Let Helm own the ServiceAccount and attach the IRSA role annotation.
  # This avoids serviceAccount.create=false failing when the SA was not created first.
  set {
    name  = "serviceAccount.create"
    value = "true"
  }

  set {
    name  = "serviceAccount.name"
    value = "aws-load-balancer-controller"
  }

  set {
    name  = "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn"
    value = aws_iam_role.lbc.arn
  }

  depends_on = [
    aws_eks_node_group.main,
    aws_iam_role_policy_attachment.lbc,
    kubectl_manifest.gateway_api,
    kubectl_manifest.aws_lbc_gateway,
    kubectl_manifest.aws_lbc_base
  ]
}

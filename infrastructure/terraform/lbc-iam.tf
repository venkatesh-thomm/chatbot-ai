
data "aws_iam_policy_document" "lbc_irsa_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
  }
}

resource "aws_iam_role" "lbc" {
  name               = "enterprise-rag-dev-lbc-role"
  assume_role_policy = data.aws_iam_policy_document.lbc_irsa_trust.json
}

resource "aws_iam_policy" "lbc" {
  name        = "enterprise-rag-dev-lbc-policy"
  description = "IAM permissions for AWS Load Balancer Controller"

  policy = file("${path.module}/aws-load-balancer-controller-iam-policy.json")
}

resource "aws_iam_role_policy_attachment" "lbc" {
  role       = aws_iam_role.lbc.name
  policy_arn = aws_iam_policy.lbc.arn
}

output "lbc_irsa_role_arn" {
  value = aws_iam_role.lbc.arn
}


data "aws_iam_policy_document" "app_irsa_trust" {
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
      values   = ["system:serviceaccount:default:enterprise-rag-api"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project_name}-${var.environment}-api-role"
  assume_role_policy = data.aws_iam_policy_document.app_irsa_trust.json
}

data "aws_iam_policy_document" "app_permissions" {
  statement {
    sid       = "ListRepositoryDocuments"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.s3_documents_bucket}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["documents/github/*"]
    }
  }

  statement {
    sid    = "AccessRepositoryDocuments"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject"
    ]

    resources = [
      "arn:aws:s3:::${var.s3_documents_bucket}/documents/github/*"
    ]
  }

  statement {
    sid     = "InvokeTitanEmbeddings"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_embedding_model_id}"
    ]
  }

  statement {
    sid       = "OpenSearchServerlessAPI"
    effect    = "Allow"
    actions   = ["aoss:APIAccessAll"]
    resources = [aws_opensearchserverless_collection.main.arn]
  }
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.project_name}-${var.environment}-api-permissions"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app_permissions.json
}

output "app_irsa_role_arn" {
  value = aws_iam_role.app.arn
}


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
    sid       = "PublishDevOpsHealthAlerts"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.devops_agent_alerts.arn]
  }

  statement {
    sid    = "PersistDevOpsMonitorState"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem"
    ]

    resources = [aws_dynamodb_table.devops_monitor_state.arn]
  }

  statement {
    sid    = "ReadEC2Health"
    effect = "Allow"

    actions = [
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceStatus"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "ReadCloudWatchMetrics"
    effect = "Allow"

    actions = [
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:GetMetricData",
      "cloudwatch:DescribeAlarms"
    ]

    resources = ["*"]
  }

  statement {
    sid    = "ReadApplicationLoadBalancerHealth"
    effect = "Allow"

    actions = [
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeListeners",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth"
    ]

    resources = ["*"]
  }

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

resource "aws_sns_topic" "devops_agent_alerts" {
  name = "${var.project_name}-${var.environment}-devops-alerts"
}

resource "aws_dynamodb_table" "devops_monitor_state" {
  name         = "${var.project_name}-${var.environment}-devops-monitor-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "monitor_id"

  attribute {
    name = "monitor_id"
    type = "S"
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

output "devops_alerts_sns_topic_arn" {
  description = "SNS topic ARN for DevOps monitor notifications"
  value       = aws_sns_topic.devops_agent_alerts.arn
}

output "devops_monitor_state_table_name" {
  description = "DynamoDB table used to suppress repeated DevOps monitor alerts"
  value       = aws_dynamodb_table.devops_monitor_state.name
}

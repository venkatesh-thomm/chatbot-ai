
resource "aws_ecr_repository" "api" {
  name                 = "${var.project_name}-${var.environment}-api"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # Allow deletion of the repository even if it contains images.

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-api"
  }
}

# Retain the latest 10 dev-tagged images.
# Expire untagged images after 7 days.
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days"

        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }

        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Keep latest 10 dev images"

        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["dev-"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }

        action = {
          type = "expire"
        }
      }
    ]
  })
}

# Allow the existing IAM user to push images
# Authorization token permission requires Resource "*".
resource "aws_iam_user_policy" "ecr_push" {
  count = var.terraform_iam_user_name == null ? 0 : 1

  name = "${var.project_name}-${var.environment}-ecr-push"
  user = var.terraform_iam_user_name

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"

        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart"
        ]

        Resource = aws_ecr_repository.api.arn
      }
    ]
  })
}

output "ecr_repository_url" {
  description = "Private ECR repository URL"
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_repository_name" {
  description = "Private ECR repository name"
  value       = aws_ecr_repository.api.name
}

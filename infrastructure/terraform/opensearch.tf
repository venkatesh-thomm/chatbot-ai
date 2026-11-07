locals {
  opensearch_collection_name = "enterprise-rag-vectors"
}

data "aws_caller_identity" "current" {}

# Security group for OpenSearch Serverless endpoint
resource "aws_security_group" "opensearch_endpoint" {
  name        = "enterprise-rag-opensearch-endpoint-sg"
  description = "Allow HTTPS from private application subnets"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from private application subnets"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.private_subnet_cidrs
  }

  egress {
    description = "Outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "enterprise-rag-opensearch-endpoint-sg"
  }
}

# OpenSearch Serverless private VPC endpoint
resource "aws_opensearchserverless_vpc_endpoint" "main" {
  name               = "enterprise-rag-vpce"
  vpc_id             = aws_vpc.main.id
  subnet_ids         = aws_subnet.private[*].id
  security_group_ids = [aws_security_group.opensearch_endpoint.id]
}

# Encryption policy
resource "aws_opensearchserverless_security_policy" "encryption" {
  name        = "enterprise-rag-encryption"
  type        = "encryption"
  description = "Encryption policy for enterprise RAG"

  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/${local.opensearch_collection_name}"]
      }
    ]
    AWSOwnedKey = true
  })
}

# Private network policy
resource "aws_opensearchserverless_security_policy" "network" {
  name        = "enterprise-rag-network"
  type        = "network"
  description = "Private VPC access only"

  policy = jsonencode([
    {
      Description = "Private access through VPC endpoint"
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.opensearch_collection_name}"]
        },
        {
          ResourceType = "dashboard"
          Resource     = ["collection/${local.opensearch_collection_name}"]
        }
      ]
      AllowFromPublic = false
      SourceVPCEs     = [aws_opensearchserverless_vpc_endpoint.main.id]
    }
  ])
}

# Vector search collection
resource "aws_opensearchserverless_collection" "main" {
  name             = local.opensearch_collection_name
  type             = "VECTORSEARCH"
  description      = "Enterprise RAG vector database"
  standby_replicas = "DISABLED"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network
  ]
}


resource "aws_iam_user_policy" "opensearch_api_access" {
  count = var.terraform_iam_user_name == null ? 0 : 1

  name = "enterprise-rag-opensearch-api-access"
  user = var.terraform_iam_user_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "aoss:APIAccessAll"
        ]
        Resource = [
          aws_opensearchserverless_collection.main.arn
        ]
      }
    ]
  })
}


resource "aws_opensearchserverless_access_policy" "main" {
  name        = "enterprise-rag-access"
  type        = "data"
  description = "Access for development IAM identity and FastAPI EKS workload"

  policy = jsonencode([
    {
      Description = "Development and FastAPI access to RAG collection"

      Principal = [
        data.aws_caller_identity.current.arn,
        aws_iam_role.app.arn
      ]

      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.opensearch_collection_name}"]

          Permission = [
            "aoss:DescribeCollectionItems",
            "aoss:CreateCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DeleteCollectionItems"
          ]
        },
        {
          ResourceType = "index"
          Resource     = ["index/${local.opensearch_collection_name}/*"]

          Permission = [
            "aoss:CreateIndex",
            "aoss:DeleteIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndex",
            "aoss:ReadDocument",
            "aoss:WriteDocument"
          ]
        }
      ]
    }
  ])

  depends_on = [
    aws_opensearchserverless_collection.main
  ]
}

output "vpc_id" {
  description = "ID of the created VPC"
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = aws_vpc.main.cidr_block
}

output "availability_zones" {
  description = "Availability Zones used"
  value       = local.azs
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "s3_vpc_endpoint_id" {
  description = "S3 Gateway Endpoint ID"
  value       = aws_vpc_endpoint.s3.id
}


output "opensearch_collection_endpoint" {
  value = aws_opensearchserverless_collection.main.collection_endpoint
}

output "opensearch_dashboard_endpoint" {
  value = aws_opensearchserverless_collection.main.dashboard_endpoint
}

output "opensearch_vpc_endpoint_id" {
  value = aws_opensearchserverless_vpc_endpoint.main.id
}

output "eks_cluster_name" {
  value = aws_eks_cluster.main.name
}

output "eks_cluster_arn" {
  value = aws_eks_cluster.main.arn
}

output "eks_cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "eks_cluster_version" {
  value = aws_eks_cluster.main.version
}

output "eks_cluster_role_arn" {
  value = aws_iam_role.eks_cluster.arn
}

output "eks_node_role_arn" {
  value = aws_iam_role.eks_nodes.arn
}


output "waf_web_acl_arn" {
  description = "Full ARN of the Enterprise RAG WAF Web ACL"
  value       = aws_wafv2_web_acl.enterprise_rag.arn
}

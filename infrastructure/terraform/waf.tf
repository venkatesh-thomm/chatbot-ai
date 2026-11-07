
resource "aws_wafv2_web_acl" "enterprise_rag" {
  name        = "enterprise-rag-dev-waf"
  description = "AWS WAF protection for Enterprise RAG Chatbot ALB"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # AWS managed common web application protection
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 10

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # AWS managed protection against known bad inputs
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 20

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "KnownBadInputs"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "EnterpriseRagWAF"
    sampled_requests_enabled   = true
  }

  tags = {
    Environment = "dev"
    Project     = "enterprise-rag"
  }
}

output "waf_web_acl_name" {
  description = "WAF Web ACL name for AWS Load Balancer Controller"
  value       = aws_wafv2_web_acl.enterprise_rag.name
}

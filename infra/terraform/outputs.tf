# ==============================================================================
# RiskWise 2.0 — Terraform Outputs
# ==============================================================================

output "vpc_id" {
  description = "ID of the created VPC."
  value       = aws_vpc.main.id
}

output "alb_dns_name" {
  description = "Public DNS name of the Application Load Balancer."
  value       = aws_lb.main.dns_name
}

output "ecs_cluster_name" {
  description = "Name of the ECS Fargate cluster."
  value       = aws_ecs_cluster.main.name
}

output "api_target_group_arn" {
  description = "ARN of the API target group."
  value       = aws_lb_target_group.api.arn
}

output "web_target_group_arn" {
  description = "ARN of the Web target group."
  value       = aws_lb_target_group.web.arn
}

output "ecs_task_role_arn" {
  description = "ARN of the IAM role assumed by running ECS tasks."
  value       = aws_iam_role.ecs_task_role.arn
}

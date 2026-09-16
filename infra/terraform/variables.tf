# ==============================================================================
# RiskWise 2.0 — Terraform Variables (Production)
# ==============================================================================

variable "aws_region" {
  type        = string
  description = "AWS deployment region. Authoritative region: ap-southeast-2."
  default     = "ap-southeast-2"
}

variable "environment" {
  type        = string
  description = "Deployment tier environment name."
  default     = "production"
}

variable "project_name" {
  type        = string
  description = "Project resource naming prefix."
  default     = "riskwise"
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the isolated VPC."
  default     = "10.0.0.0/16"
}

variable "api_cpu" {
  type        = number
  description = "Fargate CPU units for API container."
  default     = 512
}

variable "api_memory" {
  type        = number
  description = "Fargate memory (MB) for API container."
  default     = 1024
}

variable "web_cpu" {
  type        = number
  description = "Fargate CPU units for Web container."
  default     = 512
}

variable "web_memory" {
  type        = number
  description = "Fargate memory (MB) for Web container."
  default     = 1024
}

variable "api_desired_count" {
  type        = number
  description = "Desired number of API task instances."
  default     = 2
}

variable "web_desired_count" {
  type        = number
  description = "Desired number of Web task instances."
  default     = 2
}

variable "bedrock_model_id" {
  type        = string
  description = "Authoritative Amazon Bedrock Anthropic model ID."
  default     = "anthropic.claude-sonnet-4-6"
}

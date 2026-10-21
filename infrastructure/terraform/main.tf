terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" {
  region = var.region
  default_tags { tags = { Project = "SentinelAI", Environment = var.environment, ManagedBy = "Terraform" } }
}
variable "region" { default = "ap-south-2" }
variable "environment" {
  default = "dev"
  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Choose dev, staging or production."
  }
}
variable "allow_paid_resources" {
  type        = bool
  default     = false
  description = "Explicit cost gate. Keep false for code review and local validation."
}
variable "enable_services" {
  type        = bool
  default     = false
  description = "Second-stage switch: start compute only after images and platform secrets exist."
}
variable "backend_image" { default = "" }
variable "frontend_image" { default = "" }
variable "certificate_arn" { default = "" }
variable "dns_zone_id" { default = "" }
variable "domain_name" { default = "" }
variable "github_repository" { default = "" }
module "platform" {
  count             = var.allow_paid_resources ? 1 : 0
  enable_services   = var.enable_services
  source            = "./modules/platform"
  region            = var.region
  environment       = var.environment
  backend_image     = var.backend_image
  frontend_image    = var.frontend_image
  certificate_arn   = var.certificate_arn
  dns_zone_id       = var.dns_zone_id
  domain_name       = var.domain_name
  github_repository = var.github_repository
}
output "deployment" { value = module.platform }

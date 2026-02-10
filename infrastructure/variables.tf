variable "agro_bucket_name" {
  description = "The name of the S3 bucket for Bronze/Silver data"
  type        = string
}

variable "aws_region" {
  description = "AWS Region"
  type        = string
  default     = "sa-east-1"
}

variable "environment" {
  description = "The deployment environment (dev, staging, prod)"
  type        = string
  default = "dev"
}


variable "github_name" {
  description = "Your GitHub Username or Organization name"
  type        = string
}

variable "github_repo" {
  description = "The name of the repository"
  type        = string
}

variable "commodities" {
  description = "List of raw commodities to create tables for"
  type        = set(string)
  default     = ["soybean", "corn", "wheat", "oil", "usd_brl"]
}
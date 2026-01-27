terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.28"
    }
  }
  backend "s3" {
    bucket = ""
    key = ""
    region = ""
    encrypt = ""
  }
}

provider "aws" {
  region = var.aws_region
}

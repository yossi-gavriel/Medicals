variable "aws_region" {
  description = "AWS region for the Terraform state resources."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Project tag value applied to Terraform state resources."
  type        = string
  default     = "medicals"
}

variable "tags" {
  description = "Additional tags applied to supported resources."
  type        = map(string)
  default     = {}
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for MedicalClassifier Terraform state. Do not commit private names in tfvars."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid S3 bucket name."
  }
}

variable "lock_table_name" {
  description = "DynamoDB table name used by the S3 backend for Terraform state locking."
  type        = string
  default     = "medical-classifier-terraform-locks"
}

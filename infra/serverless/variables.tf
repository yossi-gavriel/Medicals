variable "aws_region" {
  description = "AWS region for the serverless MedicalClassifier stack."
  type        = string
  default     = "eu-central-1"
}

variable "project_name" {
  description = "Project tag value applied to all supported resources."
  type        = string
  default     = "medicals"
}

variable "tags" {
  description = "Additional tags applied to supported AWS resources."
  type        = map(string)
  default     = {}
}

variable "function_name" {
  description = "Lambda function name."
  type        = string
  default     = "medical-classifier-serverless"
}

variable "lambda_runtime" {
  description = "Lambda runtime."
  type        = string
  default     = "python3.11"
}

variable "lambda_architectures" {
  description = "Lambda CPU architecture. Keep this aligned with the package script target platform."
  type        = list(string)
  default     = ["x86_64"]
}

variable "lambda_package_path" {
  description = "Path to the Lambda deployment zip. Relative paths are resolved from infra/serverless."
  type        = string
  default     = "build/medical-classifier-lambda.zip"
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 60

  validation {
    condition     = var.lambda_timeout_seconds >= 1 && var.lambda_timeout_seconds <= 900
    error_message = "lambda_timeout_seconds must be between 1 and 900."
  }
}

variable "lambda_memory_mb" {
  description = "Lambda memory size in MB."
  type        = number
  default     = 1024

  validation {
    condition     = var.lambda_memory_mb >= 128 && var.lambda_memory_mb <= 10240
    error_message = "lambda_memory_mb must be between 128 and 10240."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the Lambda log group."
  type        = number
  default     = 14
}

variable "api_name" {
  description = "API Gateway HTTP API name."
  type        = string
  default     = "medical-classifier-http-api"
}

variable "api_stage_name" {
  description = "API Gateway stage name. Use $default for the default HTTP API stage."
  type        = string
  default     = "$default"
}

variable "tenants_table_name" {
  description = "DynamoDB tenants table name."
  type        = string
  default     = "medicalclassifier-tenants"
}

variable "api_keys_table_name" {
  description = "DynamoDB API key hash lookup table name."
  type        = string
  default     = "medicalclassifier-api-keys"
}

variable "projects_table_name" {
  description = "DynamoDB projects table name."
  type        = string
  default     = "medicalclassifier-projects"
}

variable "procedure_specs_table_name" {
  description = "DynamoDB procedure specs table name."
  type        = string
  default     = "medicalclassifier-procedure-specs"
}

variable "procedure_spec_versions_table_name" {
  description = "DynamoDB immutable procedure spec versions table name."
  type        = string
  default     = "medicalclassifier-procedure-spec-versions"
}

variable "classification_runs_table_name" {
  description = "DynamoDB classification runs table name."
  type        = string
  default     = "medicalclassifier-classification-runs"
}

variable "classification_results_table_name" {
  description = "DynamoDB sanitized classification results table name."
  type        = string
  default     = "medicalclassifier-classification-results"
}

variable "audit_logs_table_name" {
  description = "DynamoDB sanitized audit logs table name."
  type        = string
  default     = "medicalclassifier-audit-logs"
}

variable "api_key_hashes" {
  description = "List of SHA-256 hashes for accepted OmniScan API keys. Do not pass plaintext API keys."
  type        = list(string)
  default     = []
  sensitive   = true

  validation {
    condition = alltrue([
      for value in var.api_key_hashes : can(regex("^[a-fA-F0-9]{64}$", value))
    ])
    error_message = "Every api_key_hashes value must be a 64-character SHA-256 hex digest."
  }
}

variable "create_api_key_hashes_ssm_parameter" {
  description = "Whether to mirror the API key hash CSV into an SSM SecureString parameter."
  type        = bool
  default     = true
}

variable "api_key_hashes_ssm_parameter_name" {
  description = "SSM SecureString parameter name for the API key hash CSV."
  type        = string
  default     = "/medicals/medical-classifier/api-key-hashes"
}

variable "app_env" {
  description = "Application environment name exposed to the Lambda."
  type        = string
  default     = "prod"
}

variable "app_log_level" {
  description = "Application log level exposed to the Lambda."
  type        = string
  default     = "INFO"
}

variable "procedure_definitions_path" {
  description = "Procedure definitions path inside the Lambda package."
  type        = string
  default     = "data/procedure_definitions"
}

variable "medical_classifier_llm_provider" {
  description = "Medical classifier LLM provider, e.g. openai, openrouter, or disabled."
  type        = string
  default     = "disabled"
}

variable "medical_classifier_llm_model" {
  description = "Medical classifier LLM model."
  type        = string
  default     = ""
}

variable "medical_classifier_llm_api_key_env_name" {
  description = "Name of the provider API key environment variable used by the classifier settings."
  type        = string
  default     = "OPENAI_API_KEY"
}

variable "medical_classifier_llm_api_key_ssm_parameter_name" {
  description = "Optional SSM SecureString parameter name holding the LLM API key. The plaintext value is loaded by Lambda at runtime and is not stored in Terraform state."
  type        = string
  default     = ""
}

variable "medical_classifier_llm_timeout_seconds" {
  description = "Per-IDX LLM request timeout in seconds."
  type        = number
  default     = 15
}

variable "extra_lambda_environment" {
  description = "Additional Lambda environment variables."
  type        = map(string)
  default     = {}
}

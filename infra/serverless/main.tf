terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Project   = var.project_name
        ManagedBy = "terraform"
      },
      var.tags,
    )
  }
}

locals {
  api_key_hashes_csv = join(",", var.api_key_hashes)
  lambda_package_path = startswith(var.lambda_package_path, "/") ? (
    var.lambda_package_path
  ) : abspath("${path.module}/${var.lambda_package_path}")

  lambda_environment = merge(
    {
      APP_ENV                                           = var.app_env
      APP_LOG_LEVEL                                     = var.app_log_level
      MEDICAL_CLASSIFIER_TENANTS_TABLE                  = aws_dynamodb_table.medical_classifier_tenants.name
      MEDICAL_CLASSIFIER_API_KEYS_TABLE                 = aws_dynamodb_table.medical_classifier_api_keys.name
      MEDICAL_CLASSIFIER_PROJECTS_TABLE                 = aws_dynamodb_table.medical_classifier_projects.name
      MEDICAL_CLASSIFIER_PROCEDURE_SPECS_TABLE          = aws_dynamodb_table.medical_classifier_procedure_specs.name
      MEDICAL_CLASSIFIER_PROCEDURE_SPEC_VERSIONS_TABLE  = aws_dynamodb_table.medical_classifier_procedure_spec_versions.name
      MEDICAL_CLASSIFIER_CLASSIFICATION_RUNS_TABLE      = aws_dynamodb_table.medical_classifier_classification_runs.name
      MEDICAL_CLASSIFIER_CLASSIFICATION_RESULTS_TABLE   = aws_dynamodb_table.medical_classifier_classification_results.name
      MEDICAL_CLASSIFIER_AUDIT_LOGS_TABLE               = aws_dynamodb_table.medical_classifier_audit_logs.name
      MEDICAL_CLASSIFIER_API_KEY_HASHES                 = local.api_key_hashes_csv
      MEDICAL_CLASSIFIER_PROCEDURE_DEFINITIONS_PATH     = var.procedure_definitions_path
      MEDICAL_CLASSIFIER_LLM_PROVIDER                   = var.medical_classifier_llm_provider
      MEDICAL_CLASSIFIER_LLM_MODEL                      = var.medical_classifier_llm_model
      MEDICAL_CLASSIFIER_LLM_API_KEY_ENV_NAME           = var.medical_classifier_llm_api_key_env_name
      MEDICAL_CLASSIFIER_LLM_API_KEY_SSM_PARAMETER_NAME = var.medical_classifier_llm_api_key_ssm_parameter_name
      MEDICAL_CLASSIFIER_LLM_TIMEOUT_SECONDS            = tostring(var.medical_classifier_llm_timeout_seconds)
    },
    var.extra_lambda_environment,
  )
}

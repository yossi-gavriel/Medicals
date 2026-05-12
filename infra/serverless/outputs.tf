output "api_invoke_url" {
  description = "Base invoke URL for the HTTP API."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "classify_document_url" {
  description = "Full OmniScan-compatible classifier URL."
  value       = "${aws_apigatewayv2_stage.default.invoke_url}/v1/medical-classifier/classify-document"
}

output "lambda_function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.medical_classifier.function_name
}

output "lambda_log_group_name" {
  description = "CloudWatch log group name for Lambda logs."
  value       = aws_cloudwatch_log_group.lambda.name
}

output "table_names" {
  description = "DynamoDB table names used by the Phase 1 serverless MedicalClassifier platform."
  value = {
    tenants                 = aws_dynamodb_table.medical_classifier_tenants.name
    api_keys                = aws_dynamodb_table.medical_classifier_api_keys.name
    projects                = aws_dynamodb_table.medical_classifier_projects.name
    procedure_specs         = aws_dynamodb_table.medical_classifier_procedure_specs.name
    procedure_spec_versions = aws_dynamodb_table.medical_classifier_procedure_spec_versions.name
    classification_runs     = aws_dynamodb_table.medical_classifier_classification_runs.name
    classification_results  = aws_dynamodb_table.medical_classifier_classification_results.name
    audit_logs              = aws_dynamodb_table.medical_classifier_audit_logs.name
  }
}

output "api_key_hashes_ssm_parameter_name" {
  description = "Optional SSM SecureString parameter name containing the API key hash CSV."
  value       = length(aws_ssm_parameter.api_key_hashes) > 0 ? aws_ssm_parameter.api_key_hashes[0].name : null
}

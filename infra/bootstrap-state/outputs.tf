output "state_bucket_name" {
  description = "S3 bucket name to use as TF_STATE_BUCKET."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "lock_table_name" {
  description = "DynamoDB table name to use as TF_STATE_LOCK_TABLE."
  value       = aws_dynamodb_table.terraform_locks.name
}

output "backend_key" {
  description = "Recommended backend state key for the MedicalClassifier serverless stack."
  value       = "medical-classifier/serverless/terraform.tfstate"
}

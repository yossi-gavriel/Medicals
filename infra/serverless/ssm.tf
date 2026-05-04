resource "aws_ssm_parameter" "api_key_hashes" {
  count = var.create_api_key_hashes_ssm_parameter && length(var.api_key_hashes) > 0 ? 1 : 0

  name        = var.api_key_hashes_ssm_parameter_name
  description = "SHA-256 hash CSV for accepted MedicalClassifier API keys. No plaintext API keys."
  type        = "SecureString"
  value       = local.api_key_hashes_csv
}

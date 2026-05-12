resource "aws_dynamodb_table" "medical_classifier_tenants" {
  name         = var.tenants_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "medical_classifier_api_keys" {
  name         = var.api_keys_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "api_key_hash_prefix"

  attribute {
    name = "api_key_hash_prefix"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "medical_classifier_projects" {
  name         = var.projects_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "sort_key"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "sort_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "medical_classifier_procedure_specs" {
  name         = var.procedure_specs_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "sort_key"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "sort_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "medical_classifier_procedure_spec_versions" {
  name         = var.procedure_spec_versions_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "sort_key"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "sort_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "medical_classifier_classification_runs" {
  name         = var.classification_runs_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "sort_key"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "sort_key"
    type = "S"
  }

  attribute {
    name = "gsi1pk"
    type = "S"
  }

  attribute {
    name = "gsi1sk"
    type = "S"
  }

  global_secondary_index {
    name            = "project_created_at_index"
    hash_key        = "gsi1pk"
    range_key       = "gsi1sk"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "medical_classifier_classification_results" {
  name         = var.classification_results_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "sort_key"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "sort_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "medical_classifier_audit_logs" {
  name         = var.audit_logs_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "sort_key"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "sort_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

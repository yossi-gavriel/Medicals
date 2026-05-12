data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "lambda" {
  name               = "${var.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid = "WriteLambdaLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid = "ReadWriteMedicalClassifierTables"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:UpdateItem",
    ]
    resources = [
      aws_dynamodb_table.medical_classifier_tenants.arn,
      aws_dynamodb_table.medical_classifier_api_keys.arn,
      aws_dynamodb_table.medical_classifier_projects.arn,
      aws_dynamodb_table.medical_classifier_procedure_specs.arn,
      aws_dynamodb_table.medical_classifier_procedure_spec_versions.arn,
      aws_dynamodb_table.medical_classifier_classification_runs.arn,
      "${aws_dynamodb_table.medical_classifier_classification_runs.arn}/index/project_created_at_index",
      aws_dynamodb_table.medical_classifier_classification_results.arn,
      aws_dynamodb_table.medical_classifier_audit_logs.arn,
    ]
  }

  dynamic "statement" {
    for_each = var.medical_classifier_llm_api_key_ssm_parameter_name == "" ? [] : [1]

    content {
      sid       = "ReadMedicalClassifierLlmSecret"
      actions   = ["ssm:GetParameter"]
      resources = ["arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.medical_classifier_llm_api_key_ssm_parameter_name}"]
    }
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.function_name}-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

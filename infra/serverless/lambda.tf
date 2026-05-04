resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "medical_classifier" {
  function_name = var.function_name
  role          = aws_iam_role.lambda.arn
  runtime       = var.lambda_runtime
  handler       = "app.lambda_handlers.medical_classifier_handler.lambda_handler"
  filename      = local.lambda_package_path

  source_code_hash = fileexists(local.lambda_package_path) ? filebase64sha256(local.lambda_package_path) : null

  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb
  architectures = var.lambda_architectures

  environment {
    variables = local.lambda_environment
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda,
  ]
}


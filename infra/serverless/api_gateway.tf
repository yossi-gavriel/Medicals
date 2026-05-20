resource "aws_apigatewayv2_api" "medical_classifier" {
  name          = var.api_name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "medical_classifier_lambda" {
  api_id                 = aws_apigatewayv2_api.medical_classifier.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.medical_classifier.invoke_arn
  payload_format_version = "2.0"
}

locals {
  api_routes = toset([
    "GET /v1/customer/me",
    "PUT /v1/customer/me/storage-policy",
    "GET /v1/projects",
    "POST /v1/projects",
    "GET /v1/projects/{project_number}",
    "PUT /v1/projects/{project_number}",
    "PATCH /v1/projects/{project_number}/storage-policy",
    "GET /v1/projects/{project_number}/procedure-specs",
    "POST /v1/projects/{project_number}/procedure-specs",
    "GET /v1/projects/{project_number}/procedure-specs/{procedure_code}",
    "PUT /v1/projects/{project_number}/procedure-specs/{procedure_code}",
    "GET /v1/projects/{project_number}/procedure-specs/{procedure_code}/export/omniscan",
    "POST /v1/projects/{project_number}/procedure-specs/{procedure_code}/import/omniscan",
    "POST /v1/projects/{project_number}/procedure-specs/{procedure_code}/publish",
    "GET /v1/projects/{project_number}/procedure-specs/{procedure_code}/versions",
    "GET /v1/projects/{project_number}/procedure-specs/{procedure_code}/current",
    "POST /v1/classification-runs",
    "GET /v1/classification-runs/{run_id}",
    "GET /v1/projects/{project_number}/classification-runs",
    "POST /v1/medical-classifier/classify-document",
  ])
}

resource "aws_apigatewayv2_route" "routes" {
  for_each = local.api_routes

  api_id    = aws_apigatewayv2_api.medical_classifier.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.medical_classifier_lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.medical_classifier.id
  name        = var.api_stage_name
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigateway" {
  statement_id  = "AllowExecutionFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.medical_classifier.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.medical_classifier.execution_arn}/*/*"
}

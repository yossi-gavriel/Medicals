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

resource "aws_apigatewayv2_route" "classify_document" {
  api_id    = aws_apigatewayv2_api.medical_classifier.id
  route_key = "POST /v1/medical-classifier/classify-document"
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


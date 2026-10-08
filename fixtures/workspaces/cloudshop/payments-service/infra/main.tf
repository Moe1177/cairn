terraform {
  backend "s3" {
    bucket         = "cloudshop-terraform-state"
    key            = "payments/terraform.tfstate"
    dynamodb_table = "cloudshop-terraform-locks"
  }
}

resource "aws_sqs_queue" "payment_requests" {
  name = "payment-requests-${var.environment}"
}

resource "aws_ssm_parameter" "api_url" {
  name  = "/cloudshop/${var.environment}/payments/api-url"
  type  = "String"
  value = aws_apigatewayv2_api.payments.api_endpoint
}

data "aws_sqs_queue" "shipments" {
  name = "shipments-${var.environment}"
}

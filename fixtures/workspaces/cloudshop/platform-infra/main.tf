terraform {
  backend "s3" {
    bucket         = "cloudshop-terraform-state"
    key            = "platform/terraform.tfstate"
    dynamodb_table = "cloudshop-terraform-locks"
  }
}

resource "aws_cloudwatch_event_bus" "main" {
  name = "cloudshop-bus"
}

resource "aws_s3_bucket" "receipts" {
  bucket = "cloudshop-receipts"
}

module "dead_letters" {
  source = "terraform-aws-modules/sqs/aws"
  name   = "cloudshop-dead-letters"
}

resource "aws_iam_policy" "ops" {
  policy = jsonencode({
    Statement = [{ Effect = "Allow", Action = "sqs:*", Resource = "arn:aws:sqs:*:*:*" }]
  })
}

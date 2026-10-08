terraform {
  backend "s3" {
    bucket         = "cloudshop-terraform-state"
    key            = "reports/terraform.tfstate"
    dynamodb_table = "cloudshop-terraform-locks"
  }
}

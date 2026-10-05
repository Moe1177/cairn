resource "aws_db_instance" "main" {
  engine         = "postgres"
  instance_class = "db.t4g.medium"
}

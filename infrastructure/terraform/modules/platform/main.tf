variable "enable_services" { type = bool }
variable "region" { type = string }
variable "environment" { type = string }
variable "backend_image" { type = string }
variable "frontend_image" { type = string }
variable "certificate_arn" { type = string }
variable "dns_zone_id" { type = string }
variable "domain_name" { type = string }
variable "github_repository" { type = string }
locals { name = "sentinel-${var.environment}" }
data "aws_availability_zones" "available" { state = "available" }
data "aws_caller_identity" "current" {}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
}
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false
}
resource "aws_subnet" "private" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 10)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false
}
resource "aws_internet_gateway" "main" { vpc_id = aws_vpc.main.id }
resource "aws_eip" "nat" { domain = "vpc" }
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.main]
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
}
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  vpc_id      = aws_vpc.main.id
  description = "Public TLS entry point; HTTP only redirects to HTTPS"
}
resource "aws_security_group" "app" {
  name_prefix = "${local.name}-app-"
  vpc_id      = aws_vpc.main.id
  description = "Private ECS tasks, UI ingress only from ALB"
}
resource "aws_security_group" "data" {
  for_each    = toset(["postgres", "redis", "search"])
  name_prefix = "${local.name}-${each.key}-"
  vpc_id      = aws_vpc.main.id
  description = "Private ${each.key}, only ECS tasks may connect"
}
resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_ingress_rule" "redirect" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}
resource "aws_vpc_security_group_egress_rule" "alb" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}
resource "aws_vpc_security_group_ingress_rule" "app" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}
resource "aws_vpc_security_group_egress_rule" "app_https" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "TLS-only NAT egress for AWS APIs, image layers and configured integrations; use endpoints/egress proxy before production"
}
resource "aws_vpc_security_group_egress_rule" "app_data" {
  for_each                     = { postgres = 5432, redis = 6379 }
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.data[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}
resource "aws_vpc_security_group_ingress_rule" "data" {
  for_each                     = { postgres = 5432, redis = 6379, search = 443 }
  security_group_id            = aws_security_group.data[each.key].id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}
resource "aws_kms_key" "data" {
  description             = "Sentinel encrypted data"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}
resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_db_instance" "main" {
  identifier                      = local.name
  engine                          = "postgres"
  engine_version                  = "17"
  instance_class                  = "db.t4g.micro"
  allocated_storage               = 20
  max_allocated_storage           = 100
  storage_type                    = "gp3"
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.data.arn
  db_name                         = "sentinel"
  username                        = "sentinel"
  manage_master_user_password     = true
  master_user_secret_kms_key_id   = aws_kms_key.data.arn
  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [aws_security_group.data["postgres"].id]
  publicly_accessible             = false
  multi_az                        = var.environment == "production"
  backup_retention_period         = 7
  copy_tags_to_snapshot           = true
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name}-final"
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
  auto_minor_version_upgrade      = true
}
resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}
resource "aws_elasticache_replication_group" "main" {
  replication_group_id       = local.name
  description                = "Sentinel durable stream transport"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = "cache.t4g.small"
  num_cache_clusters         = var.environment == "production" ? 2 : 1
  automatic_failover_enabled = var.environment == "production"
  multi_az_enabled           = var.environment == "production"
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.data["redis"].id]
  snapshot_retention_limit   = 7
}
resource "aws_opensearch_domain" "main" {
  domain_name    = local.name
  engine_version = "OpenSearch_2.19"
  cluster_config {
    instance_type  = "t3.small.search"
    instance_count = 1
  }
  ebs_options {
    ebs_enabled = true
    volume_size = 20
    volume_type = "gp3"
  }
  vpc_options {
    subnet_ids         = [aws_subnet.private[0].id]
    security_group_ids = [aws_security_group.data["search"].id]
  }
  encrypt_at_rest {
    enabled    = true
    kms_key_id = aws_kms_key.data.arn
  }
  node_to_node_encryption {
    enabled = true
  }
  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-PFS-2023-10"
  }
  access_policies = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { AWS = aws_iam_role.task.arn }, Action = "es:ESHttp*", Resource = "arn:aws:es:${var.region}:${data.aws_caller_identity.current.account_id}:domain/${local.name}/*" }] })
}
resource "aws_secretsmanager_secret" "platform" {
  name                    = "${local.name}/platform"
  kms_key_id              = aws_kms_key.data.arn
  recovery_window_in_days = 30
  description             = "Populate JWT_SECRET, COLLECTOR_KEY and ADMIN_PASSWORD before starting services; values are not managed in Terraform state"
}
resource "aws_ecr_repository" "app" {
  for_each             = toset(["backend", "frontend"])
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
}
resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "Keep last 20 untagged builds", selection = { tagStatus = "untagged", countType = "imageCountMoreThan", countNumber = 20 }, action = { type = "expire" } }] })
}
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}
resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.platform.arn, aws_db_instance.main.master_user_secret[0].secret_arn] },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.data.arn }
  ] })
}
resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "search" {
  role   = aws_iam_role.task.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete"], Resource = "${aws_opensearch_domain.main.arn}/*" }] })
}
resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}
locals {
  environment = [for key, value in {
    DATABASE_HOST         = aws_db_instance.main.address
    DATABASE_USERNAME     = "sentinel"
    DATABASE_NAME         = "sentinel"
    REDIS_URL             = "rediss://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
    OPENSEARCH_URL        = "https://${aws_opensearch_domain.main.endpoint}"
    OPENSEARCH_AWS_AUTH   = "true"
    AWS_REGION            = var.region
    DEMO_ENABLED          = "false"
    AI_ENABLED            = "false"
    NOTIFICATIONS_ENABLED = "false"
  } : { name = key, value = value }]
  secrets = concat([for key in ["JWT_SECRET", "COLLECTOR_KEY", "ADMIN_PASSWORD"] : {
    name = key, valueFrom = "${aws_secretsmanager_secret.platform.arn}:${key}::"
  }], [{ name = "DATABASE_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" }])
  logs = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = "sentinel" } }
  backend = {
    name            = "api", image = var.backend_image, essential = true, user = "10001", readonlyRootFilesystem = true,
    environment     = local.environment, secrets = local.secrets, logConfiguration = local.logs,
    linuxParameters = { capabilities = { drop = ["ALL"] } },
    portMappings    = [{ containerPort = 8000, protocol = "tcp" }],
    healthCheck     = { command = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')\""], interval = 30, timeout = 5, retries = 3, startPeriod = 60 }
  }
}
resource "aws_ecs_task_definition" "app" {
  count                    = var.enable_services ? 1 : 0
  family                   = "${local.name}-app"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([local.backend, {
    name            = "frontend", image = var.frontend_image, essential = true, user = "101",
    portMappings    = [{ containerPort = 8080, protocol = "tcp" }], logConfiguration = local.logs,
    linuxParameters = { capabilities = { drop = ["ALL"] } },
    dependsOn       = [{ containerName = "api", condition = "HEALTHY" }]
  }])
  lifecycle {
    precondition {
      condition     = can(regex("@sha256:[a-f0-9]{64}$", var.backend_image)) && can(regex("@sha256:[a-f0-9]{64}$", var.frontend_image))
      error_message = "Supply immutable ECR image digests; frontend must be built with API_UPSTREAM=127.0.0.1:8000."
    }
  }
}
resource "aws_ecs_task_definition" "worker" {
  for_each                 = var.enable_services ? { pipeline = "sentinel.worker", integrations = "sentinel.integration_worker", maintenance = "sentinel.maintenance_worker" } : {}
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name             = each.key, image = var.backend_image, essential = true, user = "10001", readonlyRootFilesystem = true,
    command          = ["python", "-m", each.value], environment = local.environment, secrets = local.secrets,
    logConfiguration = local.logs, linuxParameters = { capabilities = { drop = ["ALL"] } }
  }])
}
resource "aws_lb" "main" {
  name                       = local.name
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}
resource "aws_lb_target_group" "main" {
  name        = local.name
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/healthz"
    matcher = "200"
  }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.main.arn
  }
}
resource "aws_lb_listener" "redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
resource "aws_ecs_service" "app" {
  count            = var.enable_services ? 1 : 0
  name             = "app"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.app[0].arn
  desired_count    = 1
  launch_type      = "FARGATE"
  platform_version = "1.4.0"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.main.arn
    container_name   = "frontend"
    container_port   = 8080
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  depends_on = [aws_lb_listener.https, aws_iam_role_policy.secrets]
}
resource "aws_ecs_service" "worker" {
  for_each         = aws_ecs_task_definition.worker
  name             = each.key
  cluster          = aws_ecs_cluster.main.id
  task_definition  = each.value.arn
  desired_count    = 1
  launch_type      = "FARGATE"
  platform_version = "1.4.0"
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  depends_on = [aws_ecs_service.app]
}
resource "aws_route53_record" "main" {
  count   = var.dns_zone_id != "" && var.domain_name != "" ? 1 : 0
  zone_id = var.dns_zone_id
  name    = var.domain_name
  type    = "A"
  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
resource "aws_s3_bucket" "backups" {
  bucket_prefix = "${local.name}-backups-"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
  }
}
resource "aws_s3_bucket_policy" "tls" {
  bucket = aws_s3_bucket.backups.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${local.name}-database-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.id }
  comparison_operator = "LessThanThreshold"
  threshold           = 5368709120
  evaluation_periods  = 2
  period              = 300
  statistic           = "Minimum"
  alarm_description   = "RDS free storage below 5 GiB; connect an approved SNS action before production."
}
output "region" { value = var.region }
output "ecr_repositories" { value = { for k, v in aws_ecr_repository.app : k => v.repository_url } }
output "platform_secret_arn" { value = aws_secretsmanager_secret.platform.arn }
output "database_secret_arn" { value = aws_db_instance.main.master_user_secret[0].secret_arn }
output "alb_hostname" { value = aws_lb.main.dns_name }
output "cluster" { value = aws_ecs_cluster.main.name }
output "backup_bucket" { value = aws_s3_bucket.backups.id }

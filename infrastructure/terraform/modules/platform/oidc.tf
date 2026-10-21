# Created only when a repository is explicitly configured. No access keys are generated.
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.github_repository != "" ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
resource "aws_iam_role" "github" {
  count = var.github_repository != "" ? 1 : 0
  name  = "${local.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Principal = { Federated = aws_iam_openid_connect_provider.github[0].arn },
      Action = "sts:AssumeRoleWithWebIdentity",
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:${var.environment}"
      } }
    }]
  })
}
resource "aws_iam_role_policy" "github" {
  count = var.github_repository != "" ? 1 : 0
  role  = aws_iam_role.github[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = [for repository in aws_ecr_repository.app : repository.arn] },
    { Effect = "Allow", Action = ["ecs:UpdateService", "ecs:DescribeServices"], Resource = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:service/${local.name}/*" },
    { Effect = "Allow", Action = ["ecs:RegisterTaskDefinition"], Resource = "*" },
    { Effect = "Allow", Action = ["ecs:DescribeTaskDefinition"], Resource = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/${local.name}-*:*" },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = [aws_iam_role.execution.arn, aws_iam_role.task.arn], Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } } }
  ] })
}
output "github_deploy_role" { value = try(aws_iam_role.github[0].arn, null) }

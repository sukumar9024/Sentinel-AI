# AWS deployment code — ap-south-2

**Code only. No AWS login, plan, apply, resources, or paid API calls were performed.**

`allow_paid_resources` defaults to `false`, so the platform module has zero instances by default. Keep it false. Local validation only needs the public Terraform provider download:

```sh
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
```

The code describes a VPC, two public and two private subnets, NAT, HTTPS ALB with an existing ACM certificate, private ECS/Fargate application and workers, encrypted RDS, TLS Redis, encrypted VPC OpenSearch, ECR, Secrets Manager, CloudWatch logs/flow logs, scoped IAM, optional GitHub OIDC, optional Route53 record, and an encrypted versioned backup bucket.

The default region is Hyderabad (`ap-south-2`). Region/service/instance availability and actual prices must be checked when deployment is authorized; schema validation cannot prove deployment readiness.

## Explicit requirements before a future deployment

1. Obtain approval for a budget. NAT, ALB, Fargate, RDS, Redis, OpenSearch and logs have ongoing charges. This is not a free-tier architecture.
2. Use an encrypted, private remote state backend. `backend.hcl.example` is documentation only; no state bucket has been created.
3. Build immutable x86_64 ECR images. Build the frontend with `--build-arg API_UPSTREAM=127.0.0.1:8000`; the frontend and API share one ECS network namespace. Native Compose uses `api:8000` instead.
4. Supply `backend_image` and `frontend_image` as `repository@sha256:digest`. Supply an existing validated ACM certificate in the same region. Optional Route53 settings reference an existing zone.
5. Provision the foundation first with `enable_services=false`, populate the generated platform secret with unique `JWT_SECRET`, `COLLECTOR_KEY`, and `ADMIN_PASSWORD`, publish images, then start services. Only set `enable_services=true` after secrets/images exist; that creates the task definitions and services. Split these operations into an approved deployment plan rather than blindly applying everything.
6. Use a dedicated migration/runtime database role before production. This reference injects the managed RDS bootstrap credential into the application; its permissions must be reduced before exposing real data.
7. Configure monitoring destinations and tested backups/restores. The S3 bucket does not itself schedule OpenSearch snapshots. Register an IAM snapshot role/repository and verify managed-service restore behavior separately.
8. If GitHub OIDC already exists in the AWS account, import/reuse it; do not create a duplicate provider. The trust is limited to the exact repository and named GitHub environment; configure that environment's approval rules yourself.

## Honest availability limits

One NAT gateway and one OpenSearch node are used. RDS and Redis enable their replica settings for `production`, but the overall design is still not fully highly available. The pipeline uses a global PostgreSQL lock for correctness; more worker replicas provide failover, not linear detection throughput. No managed AWS deployment, restore, failover or capacity claim has been verified.

AI and notifications remain disabled in the task definitions. Redis is protected by VPC security groups and TLS; add ACL authentication for a production deployment. Secret rotation requires task restart because ECS injects values at startup. Keep database/ALB deletion protection enabled until an explicitly reviewed teardown.

No automatic cloud apply or deploy workflow is included. CI validates code and builds/tests local containers only.

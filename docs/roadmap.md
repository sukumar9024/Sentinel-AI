# Delivery status

The local application and infrastructure-code scope requested for this project is implemented. The original 58-phase production brief remains in `original-project-brief.txt`; this status does not convert code-only AWS resources or test doubles into live production evidence.

## Implemented and locally verified

- [x] Authenticated intake, schema, redaction, bounds and rate limits
- [x] Fluent Bit JSON collection, buffering, persisted offset and authenticated adapter
- [x] PostgreSQL + Redis Streams stack, retries, DLQ, replay and broker-loss reconciliation
- [x] Normalization, 19 Git-managed detection rules, thresholds/sequences and suppression
- [x] Atomic correlation, severity escalation, asset inventory and criticality
- [x] Incident ownership, notes, lifecycle, resolution and audit history
- [x] OpenSearch indexing/mappings, text/time/request-ID search and database fallback
- [x] React analyst console, administration, rule toggles, event export and mobile layout
- [x] JWT/session authentication, refresh rotation/replay protection, revocation and RBAC
- [x] Alembic upgrades, original-database adoption and evidence foreign keys
- [x] Worker heartbeats, Prometheus alerts, Grafana provisioning and hourly retention
- [x] Read-only AI adapter with structured validation, caps, timeout and deterministic fallback
- [x] Disabled-by-default webhook/SMTP adapters with durable delivery/retry/replay
- [x] Positive/negative rule tests, API/security tests and browser workflows
- [x] Worker/search/Redis/PostgreSQL outage drills and permanent-stream-loss recovery
- [x] PostgreSQL isolated restore and OpenSearch renamed-index restore drills
- [x] Non-root images, dependency/static/image scans and CI workflow definitions
- [x] Local burst benchmark tooling and measured results

Provider adapters are implemented; live model inference and external notification delivery remain configuration-dependent and were not invoked. Host-specific Linux/Nginx/Docker collection examples must be adapted and tested on their actual monitored machines.

## Infrastructure code complete; deployment deliberately excluded

- [x] `ap-south-2` Terraform reference with explicit resource/compute activation gates
- [x] VPC, public/private subnets, HTTPS ALB and private ECS/data topology
- [x] Encrypted RDS/Redis/OpenSearch, ECR, IAM, Secrets Manager and logs
- [x] Optional GitHub OIDC/DNS, backup bucket and remote-state configuration example
- [x] Local formatting and provider-schema validation
- [ ] AWS plan/apply, paid resources, DNS/TLS activation and managed-service testing — outside authorization
- [ ] Hosted CI execution and cloud deployment — not performed

## Remaining production engineering and optional enhancements

These are explicitly outside a claim that the local lab is ready for public production:

- Approve a cloud budget; verify region/service availability and actual prices.
- Replace bootstrap database credentials, add Redis ACLs, secure remote state, and configure real backup/alert destinations.
- Resolve/review the documented ALB/HTTPS-egress scan findings for the chosen deployment exposure.
- Validate AWS secret rotation, migrations, TLS, managed snapshots/restores, failover and teardown.
- Add application MFA/OIDC, tamper-resistant audit export and independent security review.
- Design event-time watermarks/retroactive evaluation, entity partitioning, bounded large-scale state and retention.
- Measure sustained representative traffic, detection precision/recall, resource utilization and cloud cost.
- Extend UI pagination/history, dashboard time-range selection and host-specific collector coverage as needed.

Use [verification.md](verification.md) and [portfolio.md](portfolio.md) for claims supported by actual results.

# Security model

This application is a localhost security lab. Its AWS code is an undeployed reference, not a production security certification.

## Implemented controls

- Unique bootstrap secrets, owner-only `.env`, excluded secret/database/backup files, and non-root application images with a reduced runtime dependency set.
- Scrypt password hashes with random salts; signed JWTs with fixed algorithm, issuer/audience/expiry checks and server-side session/role lookup.
- Rotating hashed refresh tokens, replay-family revocation, logout revocation, user disabling and password-reset session invalidation. Browser tokens remain in memory.
- Administrator, analyst and viewer enforcement on the server. A collector key grants intake access, not management access.
- Bounded requests, events and batches; timestamp/IP validation; process-local limits in native mode and shared Redis limits in Compose. Redis rate-limit failure rejects intake rather than bypassing protection.
- Parameterized queries, escaped React text, bounded CSV export with formula-prefix protection, and audited rule toggles/user/incident/replay operations.
- Redaction before persistence, including recursive sensitive keys and common credential assignments in messages. Original evidence is preserved after redaction.
- Separate integration worker, bounded AI context/output, schema/citation validation, timeouts, request caps and stale-generation protection. Model output has no execution path.
- HTTPS webhook enforcement and SMTP STARTTLS by default. AI and notifications remain disabled until explicitly configured.
- Read-only application filesystems in Compose, dropped application capabilities, private data networks, localhost-only published UI/Grafana, and Nginx browser security headers.
- Alembic migrations, evidence foreign keys, durable retries/DLQ, leased integration tasks, broker-loss reconciliation and tested local restore tools.

## Findings and limits

The backend runtime was changed from Debian slim to Alpine, with unused installers/build tooling removed, after an image scan identified vulnerable OS/tooling packages. The final backend image scan reported no high/critical findings at the recorded scan time. This is a scanner result, not proof of absence of vulnerabilities; rerun scans when dependencies/images change.

The standalone Terraform module scan reports two intentional network-design findings: **AWS-0053** (Internet-facing ALB) and **AWS-0104** (outbound HTTPS to any address). The ALB is the intended TLS entry point; data services are private. Egress was narrowed from all protocols/ports to HTTPS plus explicit database/cache connections. Before production, consider private dashboard access and VPC endpoints/an egress proxy. These findings are recorded rather than silently suppressed.

Additional production limits:

- No MFA/OIDC application login, tenant isolation, immutable external audit archive or independent penetration test.
- The local Redis/OpenSearch services rely on isolation, with local OpenSearch security disabled. Compose environment variables are not a production secret manager.
- Redaction is best effort. Obfuscated/encoded secrets and unusual formats can escape it; safe structured logging at the source remains essential.
- Audit records cannot be edited through the management API, but database administrators can modify them. A restricted runtime database role and tamper-resistant export are required for production.
- The AWS reference uses the RDS bootstrap credential and must be changed to a restricted runtime/migration role before deployment. Redis ACL authentication and managed-service restore validation remain gates.
- Trusted rule regexes require review for complexity and false positives. Event ordering/lateness, disk quotas, high availability and sustained capacity are not fully addressed.
- Real LLM inference and third-party notification delivery were not exercised; adapters were verified with test doubles. No external messages or paid calls were made.

## Threat boundaries

Log messages and model output are untrusted evidence, never commands. Collector credentials are distinct from analyst credentials. Viewers cannot mutate incidents or administer the platform by bypassing the UI. Provider failures cannot roll back committed detection. Queue replay must not duplicate event or incident effects.

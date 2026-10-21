# Resume and interview material

## Resume bullets supported by this project

- Built SentinelAI, a FastAPI/React security observability platform using Fluent Bit, Redis Streams, PostgreSQL and OpenSearch, with 19 version-controlled detection rules and correlated incident investigations.
- Implemented durable ingestion, idempotent processing, retry/dead-letter workflows, refresh-token revocation and RBAC; tested worker/data-service outages and verified PostgreSQL/OpenSearch restores.
- Added Prometheus/Grafana monitoring, container hardening and security-check pipelines; authored gated Terraform for private AWS ECS/data services in `ap-south-2` without provisioning paid infrastructure.

A longer project description may mention the read-only local AI and notification adapters, structured evidence validation, and deterministic fallback. State that real model inference and external message delivery were not exercised. Describe Terraform as authored/validated code, not an operated AWS deployment. Hosted CI execution has not been verified; the initial publication skips CI to preserve the no-cost boundary.

## Five-minute demo

1. Show the architecture: collect → durable intake → normalize → detect → correlate → investigate, with independent integration tasks.
2. Generate the sample service's scenario through the documented Compose command, demonstrating actual Fluent Bit collection rather than only the UI's direct simulation.
3. Follow 25 failed logins → success → admin access → six forbidden requests into six alerts and one critical incident on a fresh database.
4. Show ATT&CK evidence, assignment, notes and resolution; explain why suspicious behavior is not proof of compromise.
5. Toggle a rule, inspect an asset's criticality, and demonstrate the viewer's limited access.
6. Open Pipeline health and Grafana. Explain heartbeats, retry/dead-letter state and search fallback.
7. Show the fault/restore results and Terraform validation, then explain the explicit no-cloud-deployment boundary.

Screenshots are in `docs/screenshots/`: dashboard, incident, mobile, events, rules, pipeline, assets and Grafana. They show a functioning local stack with cumulative synthetic test data.

## Measured local burst

The latest 1,000-event benign-heartbeat burst was accepted in **0.875 seconds** (about **1,143 accepted events/second**) and reached the relational event store in **11.0 seconds**. This is a short local burst, not sustained detection throughput or OpenSearch indexing latency. The benchmark does not measure alert precision/recall, CPU/memory, or cloud cost. Hardware contention and background services affect the result.

## Interview questions

- Why commit the outbox before returning `202`? What if the HTTP response is lost?
- What happens after a crash between database commit and Redis acknowledgment?
- How does the platform recover after the Redis stream itself disappears?
- Why does shared rate limiting fail intake closed during a Redis outage?
- How does a transaction lock preserve correctness, and why does it limit scaling?
- How do event time, source order, late arrivals, clock skew and NAT affect detection?
- How does a stale AI response fail to overwrite newer evidence?
- Why do schema/citation validation still require analyst verification?
- Where can notification duplicates occur despite durable delivery records?
- How would you restrict runtime database permissions, make audits tamper-resistant, and test managed-service restores before production?

Use the verification record for exact test claims. Do not invent production usage, uptime, attack detection accuracy, cloud performance or cost figures.

# Architecture and engineering decisions

## Durability and processing

Intake authenticates the collector, validates a bounded batch, redacts sensitive values, inserts durable jobs and commits before returning `202`. That response means accepted into the database, not analyzed or indexed. Collectors should retain a stable event UUID across retries; the Fluent Bit adapter derives a content-based UUID when one is absent.

Native mode drains SQLite jobs. Compose publishes their IDs into Redis Streams. A crash between publication and its database marker can duplicate delivery. Event primary keys and a transaction containing event storage, alerts, incident changes, integration jobs and job completion make replay idempotent.

Detection transactions are serialized using a PostgreSQL advisory lock or SQLite `BEGIN IMMEDIATE`. This supports safe duplicate delivery across workers, but favors correctness/failover rather than linear throughput. The lock also covers publication-state transitions. More replicas do not remove the serial detection bottleneck.

Failures roll back detection effects and persist a separate attempt count with exponential retry delay. Three pipeline failures produce a dead letter. Redis pending messages are reclaimed after 30 seconds. Published database jobs older than 60 seconds are requeued, recovering accepted work even after loss of the stream. Redis-mode rate limiting fails intake closed with `503` during a Redis outage; previously accepted jobs remain durable. Database failure prevents new acceptance.

## Integration outbox

Search, AI and notification tasks are written in the same transaction as their triggering evidence. A separate worker claims a five-minute lease, performs network I/O outside the detection transaction, then commits completion. Expired leases are reclaimable. Failed integrations retry with backoff up to five attempts, then become replayable dead tasks.

Search uses the event UUID as its document ID. AI tasks coalesce by incident with a generation number and a short debounce. If evidence changes while a model request is in flight, the old result cannot replace the newer assessment. Notifications coalesce by channel, incident and severity; escalation can create a second delivery.

External message delivery has a send/commit crash boundary. Stable delivery IDs help trace duplicates but cannot guarantee that every webhook/SMTP provider deduplicates them.

## Detection semantics

- Rules support equality, membership, substring, numeric comparison and trusted regexes.
- Thresholds count events in `[event timestamp − window, event timestamp]`.
- Entity keys contain environment, host, service and source IP, with username/host-local fallbacks. Separate environments and services never share a threshold bucket.
- Successful-login sequences require the same nonempty username. Admin-after-failure correlation is source-based; shared NATs can cause false positives.
- Related alerts join an open incident within 15 minutes. Five-minute suppression merges rule evidence. Severity escalates and never automatically downgrades; critical assets can elevate high incidents.
- Disabled rules are read from shared database state on each event. YAML definitions remain version controlled.
- Operational signals are not assigned decorative ATT&CK mappings. Technique resemblance is not proof of compromise.

Event-time windows exist, but there is no watermark or retroactive sequence evaluation. A late failure does not re-evaluate an already processed successful login. Preserve source order and measure collector clock skew. Multi-worker partitioning, a lateness policy and representative precision/recall evaluation remain production engineering work.

## Storage and retention

Alembic revisions upgrade new databases and adopt the original v0.1 schema while preserving its data. Relational constraints protect incident evidence links. SQLite WAL supports native development; the exercised Compose stack uses PostgreSQL.

OpenSearch has explicit mappings and daily event indexes. Search supports text, source, service, event type, time and request ID; an outage returns labeled relational fallback results. Indexing is eventually consistent, so a newly accepted event may appear in the database before the search index.

The maintenance worker applies configured retention hourly. Unreferenced old relational events can expire; incident-linked relational evidence is preserved. Daily OpenSearch indexes older than the retention window are deleted. Completed ingestion jobs expire separately. Incident, note and audit history are retained. A large deployment needs more efficient retention scans and explicit long-term incident/audit policies.

Incident detail returns at most 200 evidence records with a separate total. Overview aggregation, window queries and JSON evidence-ID arrays suit this lab; they are not a high-volume SIEM storage claim.

## AI and authorization

The default analysis is a deterministic evidence summary/playbook. Optional Ollama enrichment receives bounded, redacted, allowlisted evidence, validates a structured response and rejects unknown cited event IDs. A daily cap and timeout limit requests. The model has no response-action credentials or execution tools. Its output remains an unverified assessment, even after schema validation.

JWT access tokens identify a database session and user. Refresh rotation revokes the preceding session; replay revokes its family. Logout, user disabling and password changes invalidate sessions. Server-side role checks govern management actions. Browser credentials remain in memory, with single-flight refresh to avoid concurrent rotation races.

## AWS code boundary

The Terraform reference targets `ap-south-2`, with resource creation and compute activation disabled by default. It describes private ECS/data services behind TLS ALB, encrypted stores, IAM, secrets, logs and backups. It has been validated locally; no AWS login, plan, apply or live-service test was performed. See [the infrastructure README](../infrastructure/terraform/README.md) for bootstrap steps and deployment gates.

References: [Redis consumer groups](https://redis.io/docs/latest/commands/xreadgroup/), [pending reclaim](https://redis.io/docs/latest/commands/xautoclaim/), [MITRE T1110](https://attack.mitre.org/techniques/T1110/), [MITRE T1078](https://attack.mitre.org/techniques/T1078/).

# Verification record — 2026-10-16

The local stack was exercised on the macOS development host. [Machine-readable results](verification-results.json) record the final image ID, restore counts and burst measurement.

| Check | Result |
| --- | --- |
| Backend regression suite | 68 passed |
| Incident lifecycle regression after final fix | 9 API tests passed; closed resolutions cannot be cleared |
| Python lint | Passed |
| TypeScript and production frontend build | Passed |
| Playwright | Both administration/viewer and analyst investigation workflows passed; mobile view captured |
| Docker builds and complete Compose stack | Passed; private PostgreSQL/Redis/OpenSearch and workers running |
| Fluent Bit → intake → Redis/PostgreSQL → incident/OpenSearch | Passed |
| Duplicate replay and worker stop/restart | Passed |
| Search outage fallback, Redis intake rejection, PostgreSQL restart | Passed |
| Permanent stream-loss reconciliation | Passed using a stale published outbox row with the stream removed |
| PostgreSQL isolated restore | Matched 2,266 events, 5 incidents, 31 alerts, 3 notes and 42 audit records |
| OpenSearch snapshot/renamed restore | Original and restored counts both 2,266 |
| Prometheus/Grafana | Metrics and provisioned eight-panel dashboard verified; screenshot captured |
| Python/npm dependency audits | No known vulnerabilities reported at scan time |
| Semgrep | Four local security rules; zero findings |
| Final backend image scan | Zero high/critical vulnerabilities; report image ID matched the final build |
| Filesystem secret/vulnerability/configuration scan | Zero high/critical findings and zero secret findings in scanned scope |
| Standalone Terraform module scan | Two documented network-design findings: public ALB and HTTPS egress |
| Terraform formatting/provider-schema validation | Passed; backend initialization disabled |
| AWS login / plan / apply / paid resources | Not performed |
| Hosted GitHub Actions | Defined but not executed; repository not pushed |
| Real LLM / third-party message delivery | Disabled; adapter validation uses local test doubles |

## What the tests establish

Backend coverage includes positive/negative evidence for all 19 rules, correlation, deduplication, time windows, entity/account isolation, poison-event retries, concurrent replay, schema/payload limits, redaction, RBAC, session rotation/replay/logout/disable behavior, assets/rule toggles, safe export, integration leases, AI failure/schema/citation/staleness, retention and original-database upgrade.

The browser tests use the running Compose application: create an asset and viewer, toggle a rule, inspect audits, verify viewer restrictions, queue a scenario, investigate the incident, assign it, save notes, search raw evidence, inspect rules and render a mobile overview. They leave synthetic evidence and audit records in the local database.

Fault drills temporarily affect only this project's local services and restore stopped services. Broker-loss verification backdates a published row to exercise the recovery condition without waiting for a full lease period; it is not a managed AWS outage test. Restore drills create separate database/index names and preserve the originals.

## Performance scope

A 1,000-event benign-heartbeat burst was accepted in **0.875 seconds**, with a measured batch p95 of **0.193 seconds**, and reached the relational event store in **11.0 seconds**. This is about **1,143 accepted events/second for that burst**, not sustained detector throughput or full indexing latency. CPU/memory, detection precision/recall and cloud costs were not measured.

## Scan and environment limits

Scans have limited rule/database coverage and are time-specific. The filesystem scan excludes local secrets, dependencies/build caches and private backups. The standalone Terraform module scan is reported separately because the root module is disabled by its cost gate. Neither scan results nor syntax validation certify a production deployment.

Starlette emits one non-failing deprecation warning about its test-client `httpx` integration. Current pinned tests pass. Screenshots show real application/Grafana data accumulated from verification, including repeated synthetic simulations.

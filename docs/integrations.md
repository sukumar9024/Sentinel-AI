# Optional integrations

These adapters are implemented but disabled by default. Configuration is explicit; no API keys, models, webhooks or paid endpoints are provisioned automatically.

## Local AI with Ollama

Install/run Ollama yourself and make an appropriate local model available. Set `AI_ENABLED=true`, `OLLAMA_MODEL` to the installed model, and `OLLAMA_URL` to its local HTTP endpoint. Native default is `http://127.0.0.1:11434`; Compose uses `http://host.docker.internal:11434`. Recreate the API and integrations containers after changing configuration.

The integration worker sends up to ten allowlisted event samples with truncated messages, supplies a JSON schema, limits generated tokens and request time, caps daily requests, and rejects citations to event IDs outside the supplied evidence. A newer evidence generation invalidates an in-flight older result. The LLM has no shell, AWS, containment or other action tools.

Validated structure and citations do **not** prove factual correctness. The UI labels generated content as an assessment requiring analyst verification. Failed/disabled enrichment leaves the deterministic playbook available. Test coverage uses a provider double, including invalid evidence references and timeouts; a real model was not downloaded or invoked during development.

## Slack / Discord / email

Set `NOTIFICATIONS_ENABLED=true` only when you intend delivery. Supply one or more secrets through your local environment/secret manager:

- `SLACK_WEBHOOK_URL` (HTTPS)
- `DISCORD_WEBHOOK_URL` (HTTPS)
- SMTP host/port/from/to, optional username/password, `SMTP_STARTTLS=true`

The worker sends high/critical incident metadata, not raw log bodies. Each channel has a stable incident/severity delivery key; escalation may produce a second notification. Failed delivery retries with backoff up to five attempts, then enters a replayable dead state. Disabled tasks can be replayed from Administration after configuration.

There is an unavoidable send/ack crash boundary: a provider may accept a message before the worker commits completion. A retry can therefore deliver a duplicate. The stable header/Message-ID helps investigation but does not guarantee that every provider deduplicates it. No external Slack, Discord or email messages were sent during verification.

## OpenSearch

Compose connects to its private local service automatically. Native mode may set `OPENSEARCH_URL`; optional basic-auth username/password are supported, and TLS verification stays enabled. An AWS deployment uses `OPENSEARCH_AWS_AUTH=true` and task-role SigV4 signing; credentials are looked up only when that mode is explicitly enabled. No AWS signing/client call was exercised against an AWS account.

If indexing was previously disabled, run `scripts/maintenance.py search-backfill` with the correct database/search configuration. It queues stable document IDs, so retries overwrite the same document rather than duplicating evidence. Search responses identify `opensearch`, `database`, or `database-fallback`; the latter is a visible degradation, not a claim that the search cluster is healthy.

## Collection beyond the sample service

`logging/fluent-bit.conf` is an exercised JSON-file configuration. `logging/host-inputs.example.conf` documents raw host ingestion and Docker wrappers; actual Linux host paths and permissions vary. Mount the specific log files read-only, add the required environment/host/service/source metadata, persist tail state, and keep the collector key outside Git. Do not mount the Docker socket solely to read logs.

Fluent Bit chunks must fit the 512 KiB intake limit. Very large batches, malformed records, long lines and disk exhaustion require monitoring; buffering does not create unlimited capacity. The sample tail input skips lines exceeding 16 KiB, so source applications should emit bounded structured records. Stable source event UUIDs are preferred; the adapter derives a stable content ID when one is absent.

References: [Fluent Bit HTTP output](https://docs.fluentbit.io/manual/2.1/pipeline/outputs/http), [OpenSearch templates](https://docs.opensearch.org/latest/api-reference/index-apis/index-templates/), [Ollama structured outputs](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx).

---
name: sedasanj-observability-alerts
description: Add metrics, structured logs and Prometheus alerts for a new SedaSanj capability, with end-to-end request IDs. Use whenever a feature can fail or stall in production.
---

# Observability and alerts

## Existing stack (verified)

Prometheus config and rules: `sedasanj/deploy/prometheus/prometheus.yml`, `alerts.yml` (alerts such as `ApiDown`, `DispatcherDown`, `PostgresUnreachable`, `RetryableBacklog`). Logs: `sedasanj/deploy/loki/` (Loki + promtail). Dashboards/provisioning: `sedasanj/deploy/grafana/`. App metrics: `sedasanj/apps/api/app/metrics.py`. JSON logs: `apps/api/app/logging.py` (`request_id`, `tenant_id`, `call_id`).

Planned (not present): Alertmanager and receivers, scraping of `worker-provision`, `cbi_job_failures_total{kind,error_code,retryable}`, `cbi_module_*` metrics. ⚠ `LlamaServerDown` is noted in the plan as a false-positive source.

## Per-feature checklist

1. One counter for failures labeled by stable error code (low cardinality: never label by tenant, call or path).
2. One gauge/age metric for backlog or last success.
3. One alert per user-visible failure mode, with a runbook link (`sedasanj/docs/runbook.md`) and a threshold justification.
4. Logs follow `sedasanj-logging-standard`; `request_id` passes API → worker → provider calls and, for the module, `X-Request-ID` ↔ `server_request_id`.
5. Test that the metric increments on the failure path.

## Verify

`promtool check rules sedasanj/deploy/prometheus/alerts.yml` (if available); trigger the failure in a dev stack and confirm metric, log line and alert expression.

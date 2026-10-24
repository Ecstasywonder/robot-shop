# Alert Source Preflight - 23 October 2026

Status: source and EC2 unit validation only. These rules have not been applied
to Kubernetes, and no instructor incident has been performed.

## Prepared Coverage

- Cart gateway availability: 99% rolling 24-hour objective; a separate
  five-minute degradation warning requires at least 20 requests and two
  minutes above 1% 5xx. It is not a multi-window burn-rate alert.
- Missing Cart request series and missing/down Fluent Bit RED endpoint.
- Gateway 5xx warnings for web, catalogue, and payment.
- Unexpected idle web traffic during the required steady-load period.
- Robot Shop OOM termination correlated with a recent restart, crash loops,
  and unavailable desired deployment replicas, including RabbitMQ.

All rules use the existing `capstone=robot-shop` Slack route and fixed runbook
URL. Derived RED selectors restrict the trusted `log-collection` scrape
namespace. Missing telemetry and zero request denominators do not establish
successful availability.

## EC2 Validation

The EC2 workstation ran the helpers in
`Capstone 2/observability/alerting/` using `prom/prometheus:v3.7.3`:

- `test-prometheus-rules.sh`: three rules parsed; unit tests passed after
  namespace-scoping the selectors and fixtures.
- `test-operational-rules.sh`: five rules parsed; unit tests passed after
  correcting expected annotations, deployment labels, and the pending-time
  fixture. The initial fixture failures were not live cluster failures.

Fixtures exercise healthy, pending/firing, recovery, low-volume/no-data,
namespace isolation, and OOM/restart correlation behavior. No local image
downloads or cluster mutations were needed for these tests.

## Remaining Runtime Gates

1. Finish the independent load-generator stability soak before installing
   additional workloads or changing the cluster.
2. Install and validate Fluent Bit/Loki, then confirm actual derived metric
   labels and kube-state-metrics series against the rule selectors.
3. Review and server-dry-run the rules; apply them only after dependencies
   are healthy. Confirm Prometheus loaded them without evaluation errors.
4. Publish the runbook and deploy the fixed-link Slack receiver source.
5. Verify firing and recovery separately from the instructor-led drill.
   Record actual delivery and user-visible recovery; do not count the earlier
   connectivity test as the instructor incident.

This single-node stack cannot independently alert on total loss of its own
node. Host filesystem/CPU coverage is also limited because node exporter is
disabled. Tracing and logs have separate availability and retention limits;
the runbook must expose these gaps rather than promise every fault is covered.

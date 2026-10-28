# Robot Shop Monitoring Coverage

This register prevents an incident responder from assuming that every failure
has an alert. It records deployed signals, live verification from the five
student-led simulations, and explicit residual limits. Runtime status is backed
by live target, rule, and notification evidence rather than source alone.

## Deployed and live-verified coverage

| Area | Signal or source | Detects | Important limit |
| --- | --- | --- | --- |
| Kubernetes object state | kube-state-metrics and chart default rules | Replica, Pod-state, node-condition, and some PVC/object failures after exact live series/rules are confirmed | Object state is not application success. The chart default receiver is `null`, so defaults do not reach the capstone Slack route. |
| Host capacity | Kubernetes node conditions and events | Memory/disk pressure and eviction symptoms reported by Kubernetes | Node exporter is disabled. There are no promised host CPU, memory, filesystem, or network time series. |
| Gateway RED | Deployed dashboard and Fluent Bit-derived metrics for `web`, `catalogue`, `cart`, and `payment` | Gateway request rate, 5xx ratio, and latency | Observes web access events, not every internal hop. Nginx now preserves original routing attribution across `error_page` and accepts one or more leading `/` before `api`; raw request targets are not logged in incident evidence. |
| Availability | Deployed Cart, traffic-absence, Fluent Bit, crash-loop, routing, and Collector rules | Scoped availability and telemetry-blindness failures | All 10 rules were healthy and inactive after the five simulations. No full 24-hour compliance claim until 24 hours of continuous data exists. |
| Operational health | Deployed gateway, OOM, crash-loop, Deployment, and Redis StatefulSet availability rules | High-signal customer-path and Kubernetes workload failures | A crash-looping replacement can be masked by an older Ready Pod; correlate alerts with rollout generations and Pod identities. |
| Logs | Deployed Fluent Bit and Loki | Bounded search by application service and normalized level | A collector restart may cause gaps/replay; Loki is single-replica and private. The logging simulation verified post-restore collection, not uninterrupted replay. |
| Traces | Deployed payment instrumentation, OpenTelemetry Collector, and Jaeger | One payment request path and exporter/receiver troubleshooting | Collector availability is distinct from final payment 2xx. One traced service is not distributed tracing coverage for every dependency; fresh post-recovery spans, not buffered traces, are required. |
| Notifications | Alertmanager capstone child route to Breatha.org `#tscapstone` | Alerts explicitly labelled `capstone="robot-shop"` | Other chart/default alerts go to `null`. Slack connectivity does not prove an SLO rule will fire. |

## Deployed operational alert set

The deployed rules form a high-signal set. The simulations exercised Cart
availability, gateway 5xx, crash-loop, Fluent Bit availability, and Collector
availability alerts; the other listed rules were not fault-tested. Every
drill alert uses `capstone="robot-shop"`, a bounded `service`, meaningful
severity, and the fixed runbook URL for scoped routing.

| Alert intent | Scope and condition | Noise control / validation gate |
| --- | --- | --- |
| `RobotShopGateway5xxRateHigh` | Guarded 5xx ratio for `web`, `catalogue`, and `payment`, while retaining the separate Cart SLO rule | Keep a minimum request count and a `for` duration. Test zero-error, low-traffic, no-traffic, and sustained-error fixtures. |
| `RobotShopGatewayTrafficIdle` | The `web` request series exists, has observed traffic, and its rolling 10-minute rate stays zero for another 10 minutes, roughly 20 minutes from the last request | An absent series does not fire; that remains telemetry/unknown. Idle web traffic may be a load-path failure rather than an application outage. |
| `RobotShopContainerOOMKilled` | Robot Shop container has last termination reason `OOMKilled` and its restart counter increases within 10 minutes | Exclude completed Jobs. Verify kube-state-metrics reason/restart labels live; the paired conditions avoid repeatedly alerting on old OOM history alone. |
| `RobotShopContainerCrashLooping` | A Robot Shop container remains in `CrashLoopBackOff` for two minutes | Exclude completed Jobs and validate waiting-reason labels live. Correlate with rollout generation, current/previous Pod logs, probes, and OOM evidence; an older Ready replica does not clear the replacement failure. |
| `RobotShopDeploymentUnavailable` | Robot Shop desired replicas exceed available replicas for at least five minutes | Validate Deployment metrics and labels live. Alert only on declared application deployments, not transient test Pods. |
| `RobotShopRedisStatefulSetUnavailable` | Redis desired replicas exceed ready replicas for at least five minutes | Redis is a StatefulSet, not a Deployment. An absent metric is unknown rather than proof of failure; validate exact StatefulSet labels live. |
| `PaymentTraceCollectorUnavailable` | Known single `observability/otel-collector` Deployment has fewer than one available replica for two minutes, including declared zero replicas | This is tracing blindness, not proof of payment failure. The rule requires both KSM series; total series absence remains unknown and needs target/scrape investigation. |

Two candidate gaps remain deliberately unimplemented. Add a dedicated single
node NotReady alert only after confirming `kube_node_status_condition` is
scraped and the chart defaults do not already provide equivalent coverage. Add
component-specific telemetry alerts for Loki, the Collector, and Jaeger only
after each component is deployed and its normal target identity is captured.
Absence means unknown telemetry, not application failure.

Do not add broad CPU/disk alerts based on metrics that are not collected, and
do not enable node exporter merely to satisfy this list. PVC/node disk coverage
needs a separately reviewed source and live series check. Avoid optional
multi-window burn-rate or chaos tooling until the mandatory dashboard, logs,
trace, SLO alert, runbook link, and instructor drill are demonstrably complete.

## Pre-Drill Validation

Before the instructor introduces a fault:

1. Confirm all expected Prometheus targets and rule groups are loaded and that
   each query returns the documented labels.
2. Confirm the dashboard contains real traffic for all four services and that
   no-data is distinguishable from zero errors.
3. Run one bounded Loki query by service and one by error level, and capture
   the query/result without customer data.
4. Send one traced payment request and find its trace in Jaeger.
5. Exercise alert expressions with rule fixtures first. Any live notification
   test must be labelled as a test and must not be recorded as the instructor
   incident.
6. Capture a healthy baseline: Pod UIDs/restarts, request rate, 5xx ratio,
   latency, target health, and current Helm revision. Payment counters
   corroborate post-gateway accounting activity; they do not prove a completed
   purchase.

The response is robust because it detects customer impact, Kubernetes workload
state, and telemetry blindness independently. It cannot promise detection of
an arbitrary fault; unsupported host metrics, uninstrumented internal hops,
single-replica observability components, and persistent-state failures remain
explicit gaps that require operator triage and escalation.

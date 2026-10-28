# Availability Alerts

`availability-rules.yaml` is the source for the Cart gateway availability
alerts. Apply it only after Fluent Bit is collecting the gateway JSON access
logs and Prometheus shows the `robotshop_http_*` series. It is selected by the
existing `kube-prometheus-stack` release label and routed by the existing
`capstone=robot-shop` Alertmanager route to `#tscapstone`.

Before applying, confirm the live derived series have scrape label
`namespace="log-collection"` and application label `service="cart"`. The rule
selectors deliberately restrict that trusted collector namespace; it is not
the application's `robot-shop` namespace. This label check remains a runtime
gate until Fluent Bit is installed.

`CartGatewayAvailabilityDegraded` is deliberately a short-window SLO-breach
warning, not a multi-window burn-rate alert and not a claim that the 24-hour
objective has been measured. It requires at least 20 requests in five minutes,
a 5xx ratio above 1%, and two minutes of persistence. The absence alerts make
telemetry loss and absent cart traffic visible rather than turning them into
success.

Run on the EC2 cluster only after a source review:

```bash
sudo k3s kubectl apply -f observability/alerting/availability-rules.yaml
sudo k3s kubectl apply -f observability/alerting/operational-rules.yaml
```

Validate the rules from the EC2 workstation with the pinned Prometheus image;
do not download images or run containers on the local machine:

```bash
bash observability/alerting/test-prometheus-rules.sh
bash observability/alerting/test-operational-rules.sh
bash observability/alerting/test-tracing-rules.sh
```

The six operational rules add scoped gateway errors, planned-traffic idleness,
OOM/restart correlation, crash loops, unavailable Deployments, and unavailable
Redis StatefulSet replicas. Verify the live kube-state-metrics family names
and workload labels before applying them. A normal container with no prior
termination may have no last-termination reason series. The idle warning has
a ten-minute rate window and ten-minute hold, so detection is approximately
twenty minutes after the last request; silence it for a planned load pause.

The Slack receiver deliberately contains only an allowlisted fixed runbook URL
once the metrics values are reviewed. Do not interpolate arbitrary alert
annotations or Secrets into Slack templates.

`PaymentTraceCollectorUnavailable` is a source-only tracing-blindness rule for
the known single `otel-collector` Deployment in `observability`. It alerts when
both kube-state-metrics Deployment series are present and available replicas
are below one for two minutes, including declared scale-to-zero. Missing series
are unknown telemetry, not healthy tracing; the fixture expects no alert for
total series absence.

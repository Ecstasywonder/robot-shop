# Robot Shop Gateway RED Dashboard

`robot-shop-red.json` is one Grafana dashboard-as-code export, delivered by
the single `robot-shop-red` ConfigMap from `kustomization.yaml`. It uses the
Grafana sidecar's `grafana_dashboard: "1"` label in the existing namespaced
sidecar configuration. This avoids a duplicate embedded dashboard manifest.
The separate Loki datasource is in `../logging/loki-datasource.yaml`; it is
non-default and has no credentials, so it does not change the existing default
Prometheus datasource.

The dashboard is intentionally limited to RED signals for `web`, `catalogue`,
`cart`, and `payment`. It expects these gateway fixture metric names:
`robotshop_http_requests_total`, `robotshop_http_errors_total`, and
`robotshop_http_request_duration_seconds_bucket`. The aggregate panels and the
three service-split time series use a five-minute `rate()` window. Early
scrapes, scrape gaps, and a missing metric show `N/A` rather than an invented
zero. The error-counter fallback displays zero only where a request series
exists; a zero request denominator remains no-data/NaN. No availability SLI,
alert threshold, or general PII is inferred by this artifact.

The dashboard timing covers gateway requests, including health/root traffic
and the payment stub. It does not measure internal RPC timing. Before using it
as evidence, verify the actual fixture metric names, the `namespace` label, and
the Grafana Prometheus datasource UID. The derived RED queries intentionally
select `namespace="log-collection"` and use `service` as the bounded
application label because the ServiceMonitor uses `honorLabels: true`. This is
a live-label confirmation gate, not a claim that the series have already been
observed. The dashboard currently assumes UID `prometheus`; do not apply it
until that UID and the metrics are confirmed on the managed EC2 host.

## EC2-only review and application

Grafana provisions data sources and dashboards from version-controlled files;
the provider behavior is documented in Grafana's
[provisioning documentation](https://grafana.com/docs/grafana/latest/administration/provisioning/).
After the verification gate above, from the root of the canonical `robot-shop`
repository on the managed EC2 host, use the built-in K3s kubectl to render and
review the dashboard ConfigMap:

```bash
sudo k3s kubectl kustomize observability/dashboard
sudo k3s kubectl apply -k observability/dashboard
sudo k3s kubectl apply -f observability/logging/loki-datasource.yaml
```

Allow enough time for the five-minute rates to collect after a new fixture or
scrape target is introduced. For the PDF artifact, capture the provisioned
dashboard with its visible time range, panel titles, legends, and `N/A` states
when applicable; do not substitute fabricated values for first-sample gaps.

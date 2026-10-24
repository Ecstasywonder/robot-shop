# Robot Shop RED Dashboard Runtime Evidence

Date: 2026-10-24 (Africa/Lagos)

After the logging parser gate passed, the Loki datasource and the single
`robot-shop-red` Grafana dashboard ConfigMap were server-side validated and
applied in `observability`. The existing Prometheus datasource remains the
default; Loki is non-default and uses only the private in-cluster URL.

Grafana's authenticated API confirmed:

- datasource UID `loki`, name `Loki`, type `loki`, `isDefault=false`;
- dashboard UID `robot-shop-red`, title `Robot Shop - Gateway RED`, with
  seven panels.

Prometheus confirmed all four required bounded service values in
`robotshop_http_request_duration_seconds_count`, and the dashboard's
request-conditioned zero-error fallback returned `0` during the healthy
window. The dashboard is therefore provisioned from version-controlled
source and backed by live request, error, and latency series. It measures
gateway-observed traffic, including health/root traffic and the payment stub;
it is not a claim about internal RPC latency or a 24-hour availability result.

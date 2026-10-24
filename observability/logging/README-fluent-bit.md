# Fluent Bit Robot Shop log collection

This directory deploys `fluent/fluent-bit` chart `0.58.3` (Fluent Bit `5.1.3`)
as the `fluent-bit` Helm release in `log-collection`. It is a per-node
DaemonSet intentionally scoped to CRI files matching
`/var/log/containers/*_robot-shop_*.log`; it neither tails all cluster logs nor
mounts Docker container storage, machine identity, or other host paths.

The collector needs a privileged Pod Security Standards namespace solely
because Kubernetes treats a `hostPath` mount as privileged. That mount is
read-only and limited to `/var/log`. The container itself is not privileged,
has no added capabilities, cannot escalate privileges, uses a read-only root
filesystem and RuntimeDefault seccomp, and does not use host networking, PID,
or IPC namespaces. It runs as root only to read node-owned CRI log files.

## Permissions and data flow

The chart's default RBAC is disabled. Apply
[`fluent-bit-rbac.yaml`](fluent-bit-rbac.yaml) before installing the chart: it
creates a `Role` in `robot-shop` with only `get`, `list`, and `watch` on Pods,
and binds it to the collector service account in `log-collection`. Namespace
labels and annotations are disabled in the Kubernetes filter, so it does not
need namespace read permissions.

Merged JSON logs remain intact for Loki. The output uses only the bounded
`namespace`, application `service`, and normalized `level` stream labels; it
does not create labels from paths, request bodies, headers, users, or arbitrary
Pod labels. Loki is addressed only by its private in-cluster service. The
companion network policy must permit that private egress and Prometheus ingress
to ports `2021` and `2020`; it must not expose either port publicly.

This is not a log sanitization pipeline. Existing application and Nginx error
logs can contain demo identities or other data; do not use real credentials or
personal data. The read-only host mount includes other node logs, even though
the configured input reads only Robot Shop. A compromised collector could read
those files. NetworkPolicy limits egress to DNS, Loki, and the Kubernetes API;
it is not a complete node-isolation boundary. Verify the API service/node IPs
in the policy after every Terraform rebuild.

For NGINX `event=http_access` JSON events, the Lua normalizer derives bounded
RED labels: service is limited by the Lua classifier to `web`, `catalogue`,
`cart`, or `payment`; method is restricted to seven HTTP verbs plus `OTHER`;
and status must be a valid three-digit HTTP code. Duration must be finite and
non-negative, and metadata must identify the web container. Each metrics filter
uses one validated eligibility field because version 5.1.3 returns on its first
matching positive regex rule. It does not retain or derive a URL, request body, or
headers for metric labels. The observed RED series represent gateway access
events, not internal service-to-service hops. Backend severity is heuristic
except for already structured web events: recognized structured levels are
normalized, `critical` becomes `error`, and other messages are classified from
bounded error/debug keywords with an `info` fallback.

## Buffering and durability limits

Fluent Bit stores tail offsets and filesystem buffers in a `1Gi` `emptyDir`.
Filesystem buffering uses at most 16 resident chunks (typically about 32 MiB),
a 10M backlog budget, and a 128M Loki output queue; each log-to-metrics emitter
is limited to 2M. The Tail `Mem_Buf_Limit` is not the controlling memory bound
in filesystem mode. These are queue budgets, not a hard bound on total process
memory, which includes metadata, Lua, metrics, and output overhead. Observe the
384Mi container limit under sustained traffic and backpressure. Queue limits
accept loss when exhausted. The
offset database is ephemeral: a pod restart can create a gap, and
`Read_From_Head Off` prevents replay of pre-existing files when no offset is
available. This setup is therefore not a strict billing or audit pipeline.
Fluent Bit's own counter values reset when its pod restarts; use PromQL `rate`
or `increase` over a window rather than treating a raw counter as cumulative
forever.

## Install

From the root of the canonical `robot-shop` repository on the managed EC2 host,
apply the namespace and network policy maintained with the platform deployment
first, then create the narrowly scoped cross-namespace RBAC and monitor:

```bash
sudo k3s kubectl apply -f observability/logging/namespace-networkpolicies.yaml
sudo k3s kubectl apply -f observability/logging/fluent-bit-rbac.yaml
sudo k3s kubectl apply -f observability/logging/fluent-bit-servicemonitor.yaml
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm repo add fluent https://fluent.github.io/helm-charts
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm repo update
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm upgrade --install fluent-bit fluent/fluent-bit \
  --namespace log-collection \
  --version 0.58.3 \
  --values observability/logging/fluent-bit-values.yaml \
  --rollback-on-failure --wait --timeout 5m
```

If Helm fails, inspect the release, collector pods, and namespace events before
retrying. Do not delete Loki's PVC while diagnosing a Fluent Bit failure.

```bash
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm status fluent-bit --namespace log-collection
sudo k3s kubectl -n log-collection get events --sort-by=.lastTimestamp
sudo k3s kubectl -n log-collection get pods
```

The `ServiceMonitor` is deliberately hand-authored in `observability`, carries
the `kube-prometheus-stack` release label, selects only the collector service
in `log-collection`, and scrapes both the log-derived `/metrics` endpoint on
`metrics`/2021 and Fluent Bit's own `/api/v1/metrics/prometheus` endpoint on
the chart's verified `http`/2020 port every 30 seconds.

The derived-metrics endpoint uses `honorLabels: true` so the bounded application
`service` label is not overwritten by Prometheus' target `service=fluent-bit`.
The internal endpoint keeps the normal target labels. Only the trusted collector
generates the application metrics; the allowlist and label checks are essential.

## Verification

After installation, confirm that the rendered DaemonSet has no host network,
PID, or IPC settings, contains only the read-only `/var/log` host mount, and
uses the stated security context and resources. Confirm the Service remains
`ClusterIP`, the Role has no namespace or secret permissions, and the monitor
selects only `log-collection`.

Inspect the two private metrics endpoints through an authenticated local
port-forward or Prometheus targets view. Expected log-derived names begin with
`robotshop_http_` and include requests, errors, and request-duration histogram
series. A lack of traffic produces no RED data; it is not evidence that an
internal dependency was observed.

## References

The deployed image is pinned to the native linux/amd64 manifest
`sha256:07bd537485182b73af016c67dae99521e40fdf50922b39912f378c5befb8e3b1`,
resolved on EC2 for the Terraform node's architecture. This prevents tag drift;
it does not establish a vulnerability-free or signed supply chain.

- [Fluent Bit chart values for 0.58.3](https://github.com/fluent/helm-charts/blob/fluent-bit-0.58.3/charts/fluent-bit/values.yaml)
- [Fluent Bit log-to-metrics filter](https://docs.fluentbit.io/manual/data-pipeline/filters/log_to_metrics)
- [Fluent Bit Prometheus exporter](https://docs.fluentbit.io/manual/data-pipeline/outputs/prometheus-exporter)
- [Fluent Bit Loki output](https://docs.fluentbit.io/manual/data-pipeline/outputs/loki)

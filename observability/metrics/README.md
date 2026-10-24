# Resource-bounded metrics baseline

This directory installs a private, single-node metrics baseline with
[`prometheus-community/kube-prometheus-stack` chart `92.7.0`](https://github.com/prometheus-community/helm-charts/tree/kube-prometheus-stack-92.7.0/charts/kube-prometheus-stack).
That chart version packages Prometheus Operator `v0.94.1`; consult the
[chart documentation](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack) and the
[Prometheus Operator documentation](https://prometheus-operator.dev/docs/developer/getting-started/) for supported configuration.

The values are sized for one K3s `v1.36.5` node on a `t3a.xlarge` (16 GiB RAM,
60 GiB disk), alongside the voting app and Robot Shop. Prometheus retains at
most three days / 4 GB of data on an 8 Gi local-path PVC. Grafana and
Alertmanager use their own 2 Gi and 1 Gi local-path PVCs. This is a starting
budget, not capacity planning; observe disk and memory before enabling more
scrapes or increasing retention.

## Scope and coverage

Only `observability` and `robot-shop` are eligible namespaces for monitor and
rule CRs. The chart's Helm/release selectors remain enabled, so unrelated
`ServiceMonitor`, `PodMonitor`, `Probe`, and `PrometheusRule` objects are not
discovered. The voting namespace is intentionally not in the initial allowlist
because it is not yet part of the agreed platform metrics scope. This selector
limits where Prometheus reads CRs; it does not restrict the target namespaces
named by a trusted monitor. Only trusted platform operators may create or
change monitor CRs in those namespaces.

K3s embedded-control-plane targets are disabled (`etcd`, controller manager,
proxy, scheduler) along with their matching default rules. The node exporter
is also disabled: it uses host networking, PID, and filesystem mounts that do
not belong in this initial posture. The initial platform coverage is
Prometheus/Operator self-observability, Kubernetes object state, the chart's
supported Kubernetes monitors, and API-server metrics. Application scraping is
future work: a trusted operator must add release-matching monitors for Robot
Shop after reviewing their selected targets and metric cardinality. This
baseline does not provide node CPU, filesystem, or network metrics; add a
reviewed, separately scoped node-metrics design before relying on host-level
alerts.

On 22 October, the Grafana dashboard and datasource sidecars were each observed
OOMKilled with exit code 137 while capped at 64 Mi (121 restarts each); the
values raise their request to 128 Mi and limit to 256 Mi without changing CPU.
This recovers the observed underprovisioning, not a resource-capacity guarantee:
monitor the sidecars and node headroom after deployment before treating these
figures as a stable sizing decision.

Prometheus has enforced per-scrape ceilings of 50,000 samples, 100 targets,
40 labels per sample, and a 16 MB uncompressed response body. These fields are
supported by the [Prometheus Operator API](https://prometheus-operator.dev/docs/api-reference/api/)
and prevent a monitor from raising the initial resource budget unilaterally.

Fluent Bit is not part of this release. It will be installed later in a
separate, deliberately privileged namespace after its host-log requirements
and permissions have been reviewed.

## Install

Run these examples on the K3s EC2 node from the canonical `robot-shop`
repository root, not on the local machine. The Secret creation example is
for the initial install only; preserve the existing Secret and PVCs on upgrades.

Apply the namespace and same-namespace-only ingress policy before deploying.
`warn=restricted` surfaces workloads that would not meet the stricter profile
without blocking this initial baseline.

```bash
sudo k3s kubectl apply -f observability/metrics/namespace-networkpolicy.yaml
```

The policy permits ingress from observability pods only. Kubernetes also permits
traffic from a pod's own node; verify admission webhook operation during the
server-side preflight. Egress is unrestricted for API discovery and scraping.
ClusterIP-only services are not a substitute for this ingress policy.

The operator retains the chart's cluster-wide reconciliation permissions.
Only trusted cluster operators may modify its configuration or monitor CRs;
the monitor-discovery allowlist is not an operator RBAC boundary.

Generate the Grafana administrator secret directly on the cluster. Do not put
its value in `values.yaml`, shell history, manifests, or Git. The command
below generates a password in a mode-`0600` temporary file, sends that file to
the API server, and removes it without printing the password or passing it as
a command-line argument.

```bash
umask 077
GRAFANA_SECRET_FILE="$(mktemp)"
trap 'rm -f "$GRAFANA_SECRET_FILE"' EXIT
printf 'admin-user=admin\nadmin-password=' >"$GRAFANA_SECRET_FILE"
openssl rand -hex 32 >>"$GRAFANA_SECRET_FILE"
printf '\n' >>"$GRAFANA_SECRET_FILE"
sudo k3s kubectl -n observability create secret generic grafana-admin \
  --from-env-file="$GRAFANA_SECRET_FILE"
rm -f "$GRAFANA_SECRET_FILE"
trap - EXIT
```

Install the exact chart version. Helm's repository and release commands are
documented by the [Helm project](https://helm.sh/docs/helm/helm_install/).

```bash
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm repo update
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace observability \
  --version 92.7.0 \
  --values observability/metrics/values.yaml \
  --rollback-on-failure --wait --timeout 5m
```

No ingress, NodePort, LoadBalancer, or external IP is configured. Use an
authenticated cluster-operator kubeconfig and local port forwarding for
private access, following Kubernetes'
[port-forward guidance](https://kubernetes.io/docs/tasks/access-application-cluster/port-forward-access-application-cluster/).

```bash
sudo k3s kubectl -n observability port-forward --address 127.0.0.1 service/kube-prometheus-stack-grafana 3000:80
sudo k3s kubectl -n observability port-forward --address 127.0.0.1 service/kube-prometheus-stack-prometheus 9090:9090
```

## Verification

After pods and PVCs are ready, inspect Prometheus targets at
`http://127.0.0.1:9090/targets`. The intended chart/platform targets should be
`UP`; application monitors are added separately. Confirm disabled embedded-K3s jobs are absent with this
PromQL query; it should return an empty result:

```promql
up{job=~".*(etcd|controller-manager|kube-controller-manager|kube-proxy|scheduler).*"}
```

Also confirm the bound storage claims and private services:

```bash
sudo k3s kubectl -n observability get pods,pvc,svc
```

During the required EC2 render review, verify that `collectorsExclude: [secrets]`
removes kube-state-metrics Secret RBAC, and that no rendered service is public.

Never commit Grafana credentials or replace the existing-secret configuration
with plaintext values.

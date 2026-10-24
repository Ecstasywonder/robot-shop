# Private Loki baseline

This directory defines a deliberately small, private logging baseline with
[`grafana-community/loki` chart `19.0.0`](https://github.com/grafana-community/helm-charts/tree/loki-19.0.0/charts/loki), which packages Loki `3.7.8`.
It runs one monolithic StatefulSet pod in `observability`, using a 4 Gi
`local-path` PVC. The deployment has requests of 100m CPU / 256 Mi memory and
limits of 500m CPU / 1 Gi memory. It is sized as an initial workload alongside
the existing Robot Shop, voting app, and metrics stack on the one 16 GiB / 60
GiB K3s node; it is neither HA nor a production logging design.

The chart repository is exactly
`https://grafana-community.github.io/helm-charts`. Review the chart's
[official current values file](https://raw.githubusercontent.com/grafana-community/helm-charts/main/charts/loki/values.yaml) and the
[pinned 19.0.0 values file](https://raw.githubusercontent.com/grafana-community/helm-charts/loki-19.0.0/charts/loki/values.yaml)
before changing this overlay.

## Storage and retention

The overlay uses TSDB schema v13 from `2024-04-01`, one-day indexes with the
`loki_index_` prefix, and the filesystem object store rooted under `/var/loki`.
Its chunks directory and compactor working directory are therefore on the
single Binary PVC. Loki's filesystem documentation describes this storage as
appropriate for low-volume or proof-of-concept use, not production or HA:
[filesystem object store](https://grafana.com/docs/loki/latest/operations/storage/filesystem/).

Retention is 72 hours. It is enabled through the single in-process Compactor,
which writes delete requests to the filesystem and waits two hours before
deleting marked chunks. Loki requires a 24-hour index period and a configured
`delete_request_store` for compactor retention; marker files must survive a
restart, which is why this release uses persistence. See Grafana's
[retention documentation](https://grafana.com/docs/loki/latest/operations/storage/retention/).

Retention is not a disk quota: with the filesystem store, Loki does not delete
chunks based on free disk. Add a free-space alert before relying on this
deployment, and review the PVC/node capacity before increasing retention or
log volume.

## Privacy and security

There is no Ingress, Gateway API route, LoadBalancer, NodePort, or chart nginx
gateway. The only intended client endpoint is the Loki single-binary
`ClusterIP` service on port 3100. The existing `observability` NetworkPolicy
permits same-namespace ingress; this is the only reason `auth_enabled: false`
is acceptable for this educational deployment. Do not expose this service or
reuse this setting in a less restricted network.

The rendered Loki pod runs as a non-root user, uses the RuntimeDefault seccomp
profile, drops all Linux capabilities, disallows privilege escalation, and
does not mount a service-account token. The values disable the gateway,
caches, Canary, Helm test, MinIO, optional rules sidecar, simple-scalable
workloads, and distributed workloads; the sole rendered Loki container has
explicit CPU and memory limits, and no additional/init containers are defined.
Unused chart RBAC is disabled: this monolithic process does not require a
ClusterRole or Kubernetes Secret access. The image is pinned to the EC2-resolved
linux/amd64 digest
`sha256:81a6802ec4bd1b88c564494f06376889ed022998a188826190d26d2754ac2aae`.
Digest pinning prevents tag drift; it is not a vulnerability or signature proof.

Chart 19.0.0 requires both `sidecar.rules.enabled: false` and
`rbac.namespaced: true` to suppress its unused Role/Binding templates. It does
not support `rbac.create`; the single-binary sidecar switch alone does not
disable the global RBAC templates. Recheck this behavior on every chart upgrade.

Fluent Bit is intentionally outside this release. When its separately reviewed
namespace is introduced, extend the observability NetworkPolicy narrowly to
allow only the Fluent Bit pod selector to reach the Loki single-binary selector
on TCP 3100. Do not permit namespace-wide ingress from that namespace.

## EC2-only deployment and review

Run every Helm, Kubernetes, render, and verification command from the managed
EC2 host, never from a developer workstation. From the root of the canonical
`robot-shop` repository, first apply the existing observability
namespace/NetworkPolicy baseline, then perform the repository's required
rendered-manifest review. The values file itself does not create or modify a
NetworkPolicy.

```bash
sudo k3s kubectl apply -f observability/logging/namespace-networkpolicies.yaml
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm repo add grafana-community https://grafana-community.github.io/helm-charts
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm repo update
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm upgrade --install loki grafana-community/loki \
  --namespace observability \
  --version 19.0.0 \
  --values observability/logging/loki-values.yaml \
  --rollback-on-failure --wait --timeout 5m
```

During the EC2 render review, confirm exactly one single-binary StatefulSet
replica and its 4 Gi `local-path` PVC, a ClusterIP Loki service on port 3100,
no public Service/Ingress/HTTPRoute, no gateway/canary/cache/MinIO/test or
distributed workloads, and the requested security context/resource bounds.
After deployment, use an authenticated operator kubeconfig and private port
forwarding only when necessary; do not change the service type to gain access.

If the bounded Helm operation fails, inspect the release, events, and rendered
workload before retrying:

```bash
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm status loki --namespace observability
sudo k3s kubectl -n observability get events --sort-by=.lastTimestamp
sudo k3s kubectl -n observability get pods,pvc
```

`--rollback-on-failure` restores the prior Helm release automatically. Do not
delete a Loki PVC while diagnosing an installation or upgrade failure: it holds
the retained logs and compactor state. Storage deletion is a separate,
explicitly approved end-of-project action.

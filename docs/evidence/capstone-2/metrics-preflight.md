# Metrics chart preflight

Verified on the EC2 cluster host on 21 October 2026. No observability release,
namespace, Secret, or CRD was installed during these checks.

- Chart: `prometheus-community/kube-prometheus-stack`, version `92.7.0`.
- Downloaded chart SHA-256:
  `af35d3e93750ce46d90cbb6537483c8fa914f19fbffa19fbabcb2825181a0f1a`.
- Helm: `4.3.1`; render target: Kubernetes `1.36.5`.
- Helm lint: passed. Template render with CRDs: 107 objects.
- All six rendered services are ClusterIP; no Ingress or DaemonSet.
- No rendered workload uses host networking, host PID/IPC, or hostPath.
- Grafana uses a namespaced Role/RoleBinding, not a ClusterRoleBinding.
- kube-state-metrics ClusterRole does not include Secrets.
- All four Prometheus monitor/rule namespace selectors use valid label
  expressions allowing `observability` and `robot-shop`.
- The bundled Prometheus CRD schema supports these selectors and all configured
  enforced scrape ceilings.
- Final focused rerender: all eight workload/init/hook containers have CPU and
  memory requests and limits; no missing resource bounds.

EC2 scratch artifacts: `/tmp/ts-metrics-preflight/`, including the chart archive,
values, and `rendered-rerun/`. Temporary artifacts are not durable submission
evidence; the reviewed values remain under `Capstone 2/observability/metrics/`.

Security review corrected the node-exporter dependency switch, invalid namespace
selectors, Grafana cluster-wide Secret-read permissions, and the Secret collector
in kube-state-metrics. The operator still has chart-default cluster-wide
reconciliation permissions; only trusted operators may modify monitoring CRs.
This is a private, single-node educational baseline, not a production platform.

Next gate: apply the reviewed namespace ingress policy, create Grafana's Secret
directly on EC2 without printing it, install the pinned chart, and verify actual
pods, PVCs, Prometheus targets, and network isolation. Render success alone is
not runtime acceptance.

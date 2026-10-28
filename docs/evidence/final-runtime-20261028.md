# Final runtime verification — 28 October 2026

At **14:21:03 UTC**, the post-drill Kubernetes snapshot confirmed:

| Component | Ready workloads | Current restarts |
| --- | ---: | ---: |
| Robot Shop | 13 | 0 |
| Voting application | 5 | 0 |
| Observability | 8 | 0 |
| Fluent Bit | 1 | 0 |
| **Total** | **27** | **0** |

The single K3s node was Ready with no memory, disk, or PID pressure. All ten
capstone alert rules were healthy and inactive. No `ts-capstone-*` systemd
units remained. Project application and monitoring Services were private
`ClusterIP` Services without external IPs.

The machine-readable [snapshot](final-runtime-20261028.json) records pod and
node identities, readiness, restart counts, and individual rule states.

## Deployed releases

The final Helm metadata check confirmed all releases `deployed`:

| Release | Namespace | Revision | Chart |
| --- | --- | ---: | --- |
| `robot-shop` | `robot-shop` | 7 | `robot-shop-1.1.0` |
| `voting` | `voting` | 6 | `voting-app-0.1.1` |
| `kube-prometheus-stack` | `observability` | 4 | `kube-prometheus-stack-92.7.0` |
| `loki` | `observability` | 1 | `loki-19.0.0` |
| `fluent-bit` | `log-collection` | 3 | `fluent-bit-0.58.3` |

## Recovery evidence

All five student-led fault types produced their expected alerts and were
restored. Each completed case includes at least 15 minutes of recovery
observation; the [postmortem index](../postmortem.md) links the individual
timelines and raw evidence directories.

After logging restoration, fresh Loki entries were verified and both collector
endpoints had `up=1` across 30 samples in a 15-minute window. The replaced
collector's ephemeral tail database and buffer imply a collection gap; replay
and uninterrupted log delivery are not claimed.

During the tracing outage, 13 payment gateway HTTP 200 events were counted in
the defined post-settling window while saved Jaeger observations showed no new
span starts. A span starting after restoration then confirmed new trace
collection. The final tracing observation ended at 14:12:55 UTC with cleared
alerts, positive payment-response metrics, and fresh spans. At 14:20:08 UTC,
Collector availability was one across 30 samples in the preceding 15 minutes.

This is student-led simulation and runtime evidence. No instructor-led drill
has been performed, and TS Academy decides whether these exercises satisfy
that course requirement. Collection gaps and earlier attribution defects mean
this record does not certify a complete 24-hour SLO window.

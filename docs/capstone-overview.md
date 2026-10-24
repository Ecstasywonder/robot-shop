# TS Academy Capstone 2 Overview

Status as of 24 October 2026 (Africa/Lagos): this is personal course work in
the `Ecstasywonder/robot-shop` fork. Robot Shop runs on the same
default-VPC K3s cluster used for the voting-app capstone. Manual downloads,
installs, builds, and validation run on the EC2 environment; GitHub-hosted
runners are approved for CI. Services remain private `ClusterIP` services:
no public load balancer or autoscaling was added for this course scope.

The instructor did not deliver starter templates/configurations, so the
repository contains equivalent, authored configuration and documentation.

## Reviewer Navigation

- [Deployment and stability](memory-stability.md), including the
  [load-generator incident](incidents/load-generator-oom.md) and
  [three-hour soak evidence](evidence/load-oom-fix.md). The unchanged
  two-user load completed 340 samples, 2,497 additional purchases, and no
  restart while retaining its 200m CPU and 256Mi memory limits; a later
  observation also remained restart-free for more than seven hours.
- [Metrics](../observability/metrics/README.md) and the exported
  [RED dashboard](../observability/dashboard/README.md). The
  `kube-prometheus-stack` Helm release is installed at revision 4. Grafana
  API verification confirms the seven-panel `robot-shop-red` dashboard, and
  live request/latency series cover all four monitored services.
- [Logging](../observability/logging/README-fluent-bit.md). Loki and one
  Fluent Bit collector are installed and Ready. Service/level searches and
  a clearly labelled synthetic error-log check passed; see the
  [runtime evidence](evidence/logging-runtime.md). The temporary fixture
  was removed and is not an application incident or instructor drill.
- [Tracing](../observability/tracing/README.md). The private Collector and
  Jaeger are deployed, and normal synthetic traffic produced 20 recent
  `payment.pay` spans through the custom payment image. See the
  [runtime evidence](evidence/tracing-runtime.md); the in-memory trace store
  remains a course demonstration rather than durable production storage.
- [Availability policy](slo-error-budget.md),
  [alert rules](../observability/alerting/README-alerts.md),
  [monitoring coverage](monitoring-coverage.md), and the responder
  [runbook](runbook.md).
  Slack connectivity to `#tscapstone` was user-confirmed. The fixed-link
  receiver is deployed and all nine reviewed rules are loaded without
  evaluation errors. The user confirmed the latest explicitly labelled
  connectivity test and opened its runbook link. This is not drill evidence.

## Remaining Course Gates

The instructor fault has not yet been scheduled. The required incident drill,
alert evidence during that drill, and the blameless postmortem remain open.
The load-generator OOM write-up is supplemental capacity evidence, not a
replacement for that instructor-led drill. The planned monitoring covers
customer-path RED signals, workload failures, and telemetry blindness, with
known limits recorded in the coverage document rather than promising detection
of every possible fault.

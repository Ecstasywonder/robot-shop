# TS Academy Capstone 2 Overview

Status as of 28 October 2026 (Africa/Lagos): this is personal course work in
the `Ecstasywonder/robot-shop` fork. Robot Shop runs on the same
default-VPC K3s cluster used for the voting-app capstone. Manual downloads,
installs, builds, and validation run on the EC2 environment; GitHub-hosted
runners are approved for CI. Services remain private `ClusterIP` services:
no public load balancer or autoscaling was added for this course scope.

The supplied brief did not include separate starter configuration files.
Equivalent, authored configuration and documentation are included.

## Reviewer Navigation

- [Deployment and stability](memory-stability.md), including the
  [load-generator incident](incidents/load-generator-oom.md) and
  [three-hour soak evidence](evidence/load-oom-fix.md). The unchanged
  two-user load completed 340 samples, `sold_count_total` increased by 2,497
  (not a completed-purchase count), and no
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
  Jaeger are deployed. The 24 October verification found 20 recent
  `payment.pay` spans through the custom payment image. See the
  [runtime evidence](evidence/tracing-runtime.md); the in-memory trace store
  remains a course demonstration rather than durable production storage.
- [Availability policy](slo-error-budget.md),
  [alert rules](../observability/alerting/README-alerts.md),
  [monitoring coverage](monitoring-coverage.md), and the responder
  [runbook](runbook.md).
  Slack connectivity to `#tscapstone` was user-confirmed. The fixed-link
  receiver is deployed. The current monitoring set has 10 capstone alerts,
  all verified healthy and inactive after the
  student-led simulations. The 24 October implementation checkpoint remains
  documented in the linked evidence. The earlier nine-rule checkpoint was
  validated without evaluation errors. Robot Shop is at Helm revision 7 and
  Fluent Bit at revision 3. The user confirmed the 24 October explicitly
  labelled connectivity test and opened its runbook link. This is not drill
  evidence.

## Current drill and course status

Five student-led simulations are complete; their aggregate
[postmortem](postmortem.md) and [submission hub](submission.md) link the
individual records. No instructor-led drill has been performed. The
load-generator OOM write-up remains supplemental capacity evidence, not a
replacement for an instructor-led drill. The [final runtime evidence]
(evidence/final-runtime-20261028.md) and [repository structure audit]
(repository-structure-audit.md) record the completed 28 October close-out.
Course acceptance remains open. The monitoring covers customer-path RED
signals, workload failures, and telemetry blindness, with known limits recorded
in the coverage document rather than promising detection of every fault.

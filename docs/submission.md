# TS Academy DevOps capstone submission hub

This page is the public navigation point for the two personal course forks and
their supporting evidence. Manual installs, builds, and runtime validation were
performed on the project EC2 environment; GitHub-hosted runners run the CI jobs.

## Repositories

| Capstone | Repository | What to review |
| --- | --- | --- |
| Capstone 1: Ship It | [Ecstasywonder/example-voting-app](https://github.com/Ecstasywonder/example-voting-app) | Docker Compose, Terraform-managed K3s, Helm deployment, GitHub Actions CI/CD, security checks, rollback evidence, and README. |
| Capstone 2: Observe It | [Ecstasywonder/robot-shop](https://github.com/Ecstasywonder/robot-shop) | Private K3s deployment, metrics/dashboard, logging, tracing, alert routing, runbook, stability evidence, and this drill material. |

Both repositories are personal forks of the course-assigned upstream projects.
The submitted DevOps configuration, deployment work, automation, monitoring,
runbooks, and evidence are maintained in those forks; the upstream application
source remains attributed to its respective project.

## Capstone 2 evidence map

- [Overview](capstone-overview.md)
- [Memory stability and load-generator OOM correction](memory-stability.md)
- [Load-generator incident write-up](incidents/load-generator-oom.md)
- [Metrics and dashboard configuration](../observability/metrics/README.md)
  and [runtime dashboard evidence](evidence/dashboard-runtime.md)
- [Fluent Bit and Loki logging](../observability/logging/README-fluent-bit.md)
- [OpenTelemetry and Jaeger tracing](../observability/tracing/README.md)
- [Alert rules](../observability/alerting/README-alerts.md),
  [monitoring coverage](monitoring-coverage.md), and [responder runbook](runbook.md)
- [Completed student-led simulations](drills/README.md) and
  [operator safety guide](drills/operator-guide.md)
- [Current runtime evidence](evidence/final-runtime-20261028.md) and
  [repository structure audit](repository-structure-audit.md)

## Incident-drill status

Package prepared 28 October. Three student-led Cart simulations have recovered;
the third (`20261026-cart-retest-02`) observed
`CartGatewayAvailabilityDegraded` with `service=cart` after the revision 7
leading-slash mapping fix. The first two recovered runs remain documented as
learning evidence because their scoped Cart alert did not fire. Catalogue
crash-loop run 03 also recovered and passed after 16 minutes 54 seconds of
post-restore observation; its earlier two attempts remain documented as safety
learning. The Catalogue Service black-hole simulation also recovered and
passed, with its canonical archive transfer completed; Fluent Bit and
OpenTelemetry Collector also recovered and passed. They are student-led,
controlled simulations. No instructor-led drill has been performed. Whether any
of them satisfy an instructor-led requirement remains a TS Academy decision.


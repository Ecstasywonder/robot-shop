# Student-led simulation matrix

This records five completed student-led controlled simulations for stability,
observability, and serviceability practice. They are separate from the
instructor-led incident drill required by the course; no instructor-led drill
has been performed. TS Academy decides whether any student-led work may count
toward that requirement.

The current runner approved for future controlled exercises is SHA-256
`eece29c28b43f7471cbded3840003e2601c880641860a4a653fd18cb739230c9`,
and the current observer is SHA-256
`d2cdfe3f8b4f7c36056db73c0e535cc30a07856855cee32a399a35992491c6fb`.
The runner test SHA-256 is
`4a1cbc0b99f9c13435a62db43f04ce22f232a87fc50da9b461d7746c593bcb6c`.
EC2 validation recorded 29 non-root runner tests with two expected skips, 29
root tests with zero skips and two real timers, plus 14 unchanged observer
tests. The runner's only behavioral change accepts API omission of an explicit
probe `initialDelaySeconds: 0`; its serialization regression still rejects
third-party command drift. Server-side dry-run and live pre/post checks verified
the same UID `f6eb...416b`, resource version `319640`, generation `3`, and
absent command/probe. Independent review approved this version on 28 October.
The observer's sequential telemetry queries remain bounded; the independent
runner watchdog remains the rollback guard. Historical case records retain
their earlier runner and observer hashes. See the
[operator safety guide](operator-guide.md).

| Completed simulation | Scoped injected condition | Observed objective | Safety boundary | Status |
| --- | --- | --- | --- | --- |
| `cart-scale-zero` | Scale the `robot-shop/cart` Deployment from one replica to zero. | Cart gateway availability degradation and a Cart alert. | Automatic rollback within six minutes; no persistent data is changed. | Three recovered runs; third run fired `CartGatewayAvailabilityDegraded` with `service=cart`; final state restored |
| `catalogue-crashloop` | Add an intentionally failing command and readiness probe to the Catalogue Deployment. | Crash-loop signal while the existing ready Catalogue Pod stays available. | Atomic two-field rollback within four minutes. | Run 01 aborted and archived; run 02 stopped pre-mutation; run 03 recovered and passed |
| `catalogue-service-blackhole` | Point the first Catalogue Service port at unused port `65000`. | Gateway 5xx signal while workloads remain Ready. | Restore only the Service target port within five minutes. | Recovered and passed |
| `fluent-bit-unschedulable` | Give the Fluent Bit DaemonSet an impossible node selector. | Logging/RED telemetry blindness alert. | Restore the selector within eight minutes; a transient log-collection gap is expected and documented. | Recovered and passed |
| `otel-collector-scale-zero` | Scale the OpenTelemetry Collector Deployment from one replica to zero. | `PaymentTraceCollectorUnavailable`; payment customer-path evidence remains distinct from tracing availability. | Restore one Collector replica within four minutes. | Recovered and passed |

For every simulation, evidence must record the baseline, exact timestamps,
injected field, alert and notification outcome, bounded recovery, workload and
node health, and at least 15 minutes of healthy observation after rollback.
All five student-led simulations recovered and passed. The Cart record retains
two earlier partial-attribution attempts, and the Catalogue record retains two
earlier safety attempts. No instructor-drill credit is inferred from these
student-led outcomes. Each completed outcome has a blameless case record and
aggregate postmortem.

The [current runtime evidence](../evidence/final-runtime-20261028.md) and
[repository structure audit](../repository-structure-audit.md) record the final
28 October state. All eight run archives are canonical EC2 evidence; this local
overlay is not claimed to include every raw artifact.

# Student-led simulation postmortem index

This is a blameless aggregate of five student-led controlled simulations. It
does not represent an instructor-led incident drill or acceptance decision.
Detailed timelines, safeguards, and raw-evidence status remain in each case
record.

## Outcomes

| Simulation | Outcome | Case record |
| --- | --- | --- |
| Cart scale to zero | Recovered; the third run fired the scoped Cart alert | [Cart record](drills/cart-scale-zero.md) |
| Catalogue crash loop | Run 03 recovered and passed; two earlier safety attempts informed the fix | [Catalogue record](drills/catalogue-crashloop.md) |
| Catalogue Service black hole | Recovered and passed | [Routing record](drills/catalogue-service-blackhole.md) |
| Fluent Bit unschedulable | Recovered and passed | [Logging record](drills/fluent-bit-unschedulable.md) |
| OpenTelemetry Collector scale to zero | Recovered and passed | [Tracing record](drills/otel-collector-scale-zero.md) |

At `2026-10-28T14:21:03.245853Z`, independent verification found 27 Ready
workloads, zero restarts, Ready nodes without pressure, all 10 rules healthy
and inactive, no `ts-capstone` units, and only private ClusterIP project
Services with no external IPs.

## Summary of observed impacts

The Cart, Catalogue crash-loop, and Catalogue routing exercises produced their
intended scoped availability or gateway signals and restored through independent
watchdogs. The logging exercise proved alerting and post-restore collection
health; the tracing exercise proved telemetry loss while payment HTTP 200 events
continued, then verified a fresh post-restore span. All completed recovery
windows recorded `critical=[]` and bounded healthy-service evidence.

The tracing run recorded one baseline plus 47 samples (48 JSONL lines). Its
final sample at `14:12:55Z` was 21 minutes after restore and 20 minutes 03
seconds after alert clearance, with positive payment 2xx rate `0.074074/s`, 23
spans (latest start `1793196771565656122`), and no RED error series while
requests were positive. At `14:20:08Z`, Collector availability had minimum one
for 15 minutes with 30 KSM samples; the replacement Pod retained its UID with
zero restarts and fresh spans/payment traffic remained present. The observer
naturally completed its 1,500-second period and its unit was garbage-collected;
the later `not loaded` stop result is normal completion, not a failure.

## Findings and corrective actions

- Nginx normalized routing while preserving Locust's double-leading-slash
  `$request_uri`, bypassing the original `^/api` attribution map. The deployed
  `^/+api` mapping correctly attributed the third Cart retest.
- Kubernetes may omit an explicit readiness-probe `initialDelaySeconds: 0`.
  The runner now normalizes that expected representation while still refusing
  third-party command drift; lifecycle validation covers terminal archival
  without weakening restore guards.
- Unknown patch outcomes remain protected by frozen state, independent timers,
  and field/identity checks. Fresh probe validation and server-side dry-run
  guard future mutation.
- Tracing recovery requires a fresh span after restoration, not merely buffered
  historical traces. The run verified this distinction with timestamps only.

## Residual limits and course status

Fluent Bit tail DB/buffer reset means a temporary collection gap or loss remains
possible; no uninterrupted collection or replay is claimed. These exercises do
not establish a full 24-hour SLO result. No instructor-led drill has been
performed, and TS Academy alone determines whether any student-led evidence can
satisfy course acceptance. The [structure audit](repository-structure-audit.md)
completed on 28 October. Archives are canonical operational evidence on EC2,
not a claim that all raw artifacts are locally overlaid or publicly published.
See the [current runtime evidence](evidence/final-runtime-20261028.md).

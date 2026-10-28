# Load generator OOM incident - 23 October 2026

## Summary

During the Robot Shop steady-load exercise, the `load` generator repeatedly
restarted after Kubernetes terminated its container with `OOMKilled` (exit
137). This interrupted synthetic test traffic. It was not a customer-facing
outage: the affected workload is the course load generator, and this record
does not make an availability claim for Robot Shop.

The event was a **container limit reached** event, not node memory
overcommit. The load cgroup retained its existing 256 MiB memory limit while
the node had available capacity. The primary cause was materialising large
shipping-city JSON arrays in memory before choosing one city.

This is a supplementary postmortem for an actual engineering incident. It is
not the required instructor-led incident drill; the instructor-drill
postmortem in `docs/postmortem.md` remains pending until the instructor
introduces a fault.

## Impact

- Scope: the standalone `load` pod and the synthetic traffic it generates.
- User impact: test traffic paused whenever the generator was restarted; no
  real customer impact or availability duration has been established here.
- Data impact: none identified. The Redis PVC identity was unchanged through
  the replacement rollout and validation.

## Timeline (UTC)

- **Before 23 October:** the original `load` pod repeatedly restarted. A
  captured termination was `OOMKilled` / exit 137; restart intervals varied
  from roughly 11-15 minutes to one observed 91-minute interval.
- **23 October, investigation:** the exact pinned image showed that the
  25-country selection can retrieve an 18,239,043-byte U.S. city response.
  Calling `.json()` retained and decoded the full array before selecting one
  record. A representative two-client fixture reached 259,846,144 bytes,
  leaving about 8.2 MiB below the 256 MiB cgroup limit.
- **16:04-16:27:** V2 introduced streaming and kept memory near 33-38 MiB,
  but its character-by-character parser reduced request throughput under the
  unchanged 200m CPU limit. It was deliberately superseded; it was not
  accepted as the fix.
- **16:31:41:** V3 was rolled out in pod `load-5855488db7-4s868`, preserving
  the pinned image, two users, 200m CPU, and 256 MiB memory limit.
- **16:32:15-19:32:17:** the owned three-hour sampler completed successfully:
  340 healthy samples, zero restarts, a `sold_count_total` increase of 2,497
  (not a completed-purchase count), zero sampled
  HTTP errors, and 34 comparable five-minute traffic windows.
- **23:10:** an independent recheck found the same pod running for more than
  six hours with zero restarts. Its cgroup peak was 68,870,144 bytes and all
  cgroup OOM counters remained zero.

## Cause and contributing conditions

The generator used `client.get(...).json()` for shipping-city responses. This
created a high transient allocation when a large country response arrived,
and overlapping work from two Locust users left too little headroom beneath
the existing container limit. The large U.S. response and the two-user load
were contributing conditions, not mistakes by an individual.

Locust reporting-state retention was investigated but was not the primary
cause. The grouped HTTP path bounded request-route cardinality, and the
large-response fixture directly demonstrated the memory amplification. Node
pressure was also ruled out by the available node memory during the event.

## Resolution and verification

V3 streams each cities response in 16 KiB chunks, incrementally decodes UTF-8,
keeps one bounded city record, and reservoir-samples uniformly across the
complete response. It preserves all countries and does not truncate data.
The parser records full stream timing and consumed bytes, closes each response
on every path, and rejects malformed or oversized records with bounded error
messages.

An hourly cooperative Locust reporting-state reset is retained as a secondary
long-run guard; it was not presented as the root-cause fix. The V3 fixture
peaked at 46,354,432 bytes under the same 200m CPU / 256 MiB memory budget.
The three-hour soak and later independent check provide bounded confidence,
not a guarantee of infinite uptime.

## What helped

- Kubernetes termination status and cgroup evidence distinguished a container
  limit from node overcommit.
- Testing against the exact pinned image and original resource limits made the
  large-response behavior reproducible.
- The sampler checked restart count, workload readiness, memory,
  `sold_count_total` progress, and web request/error evidence together.
- V2 was stopped when it harmed throughput rather than being accepted solely
  because it avoided OOM kills.

## What did not help enough

- A short readiness check did not cover the observed 91-minute failure window.
- Treating periodic statistics reset as the likely cure would have missed the
  large-response allocation path.
- The first streaming implementation avoided OOM but consumed too much CPU;
  memory safety and traffic performance both needed validation.

## Actions

| Status | Action | Owner | Due |
| --- | --- | --- | --- |
| Done | Keep V3 streaming parser, bounded records, and resource limits unchanged. | Application/DevOps owner | 23 October 2026 |
| Done | Retain the three-hour soak summary and independent cgroup recheck as incident evidence. | DevOps owner | 24 October 2026 |
| Done | Add memory, restart, readiness, request-rate, error-rate, and `sold_count_total`-progress checks to the operating evidence. | Observability owner | 24 October 2026 |
| Planned | Exercise the alerting and runbook during the instructor-provided fault, and record the separate required postmortem. | Course participant with instructor | At instructor scheduling |
| Planned | Reassess memory behavior after any change to city payload shape, user count, pinned image, or resource limits. | Application/DevOps owner | Before the related rollout |

## Evidence

- [Diagnosis](../evidence/load-oom-diagnosis.md)
- [Fix and validation](../evidence/load-oom-fix.md)
- [Aggregate soak summary](../evidence/load-oom-soak/summary.json)

### Metric erratum

The frozen sampler's historical `purchase_growth` field records growth of
`sold_count_total`, not completed purchases. The frozen payment image was not
independently inspected, so its historical increase does not establish
item-unit or post-gateway semantics. The separately verified current payment
source increments `sold_count_total` by non-`SHIP` item quantity after gateway
processing and before queue publication, cart deletion, and the final HTTP 200;
`units_sold_count` counts observations reaching that block. The recorded
historical numbers are preserved, but are not completion proof.

# Student-led drill safety validation — 25 and 28 October 2026

This validates the drill tooling, not the outcome of a simulation or acceptance
of the instructor-led requirement. All runtime tests ran on EC2.

## Approved tools for subsequent runs

- Runner SHA-256: `eece29c28b43f7471cbded3840003e2601c880641860a4a653fd18cb739230c9`.
- Runner test SHA-256: `4a1cbc0b99f9c13435a62db43f04ce22f232a87fc50da9b461d7746c593bcb6c`.
- Observer SHA-256: `d2cdfe3f8b4f7c36056db73c0e535cc30a07856855cee32a399a35992491c6fb`.
- Observer test SHA-256: `d98d5e5769790b1b925da6ed8d0c7d06fa5a5329e0d93298fae6140befaba028`.

The current runner passed 29 non-root tests with two expected skips and 29 root
tests with zero skips, including two real timers. The observer remains unchanged
and passed 14 tests, including RFC3339 Jaeger query bounds. The runner change
only normalizes an expected readiness probe by omitting explicit
`initialDelaySeconds: 0` when the API omits it. A serialization regression
proves that third-party command drift still refuses restoration. Kubernetes
server-side dry-run and live pre/post checks verified the unchanged UID
`f6eb...416b`, resource version `319640`, generation `3`, and absent
command/probe. Compilation with warnings treated as errors passed on EC2.
Independent source review approved the runner on 28 October.

The previously approved runner
`4be7bd3ec9a7c9cb4107348c9d60cab395ba31ee01c0f68419aad8ec090c89d3` and
its test SHA-256
`78a657ccc350c549230c3c18e6b321970f2588e48aa9ac53321f4bfb1ba013f0` remain
historical validation evidence; completed case records retain their own hashes.

An unchanged-baseline smoke test exercised the frozen root-owned runner through
the actual systemd sandbox and Kubernetes client. Cart remained at one replica.

## Safety boundaries

The five cases have fixed targets, owned fields, and maximum fault durations.
The runner freezes its reviewed source and captures object identity before
arming a separate systemd rollback timer. Atomic UID/resource-version/field
guards prevent overwriting a replacement object or a third party's owned-field
change. Restoration preserves unrelated edits. Terminal runs cannot mutate
workloads again. Only one run may be active.

The observer binds its run ID and case to the protected frozen runner, compares
node identities and unrelated pod readiness/restarts, and requests emergency
restoration before collecting supplemental telemetry on a critical change.
Its sequential telemetry requests have bounded timeouts but can delay the next
health poll. It is supplemental: Prometheus/Alertmanager continue independently,
and the separately scheduled rollback watchdog limits the injected fault.

## First-run findings retained

The first cart run used runner `6cba858` and observer `72f5d141`, before the
above corrections. Its actual evidence is retained unchanged. It exposed:

1. Nginx's internal error-page redirect changed `$uri`, attributing failed cart
   requests to `web`; the general gateway alert detected the outage, while the
   cart-specific alert did not. A separate EC2 regression subsequently verified
   the original-request classification fix for cart, catalogue, and payment.
2. Manual rollback restored Cart but reported timer-cleanup failure when the
   never-started service was already absent. Both recovery units were verified
   `not-found/inactive/dead`; the original frozen runner's baseline-only
   watchdog entry recorded restoration without a Kubernetes patch. The new
   runner accepts that stop result only after proving both units inactive,
   dead, and free of queued jobs.
3. The observer sent Unix seconds to Jaeger's RFC3339 query bounds, producing
   null trace summaries. A corrected independent query found payment spans;
   the new observer uses tested UTC RFC3339 bounds.

Live simulation outcomes, recovery windows, and corrective deployments are
recorded separately in the drill postmortems.

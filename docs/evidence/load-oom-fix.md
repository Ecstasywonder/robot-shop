# Load generator OOM fix rollout

Test date: 2026-10-23 (UTC). Final recheck: 2026-10-24 (Lagos),
`2026-10-23T23:10Z` UTC.

## Final Result: Passed

The owned three-hour sampler completed successfully at
`2026-10-23T19:32:17Z`: `pass=true`, no failures, systemd `Result=success`,
`ExecMainStatus=0`, and unit inactive. It collected 340 samples over 10,800
seconds, retaining the same pod UID and zero restarts throughout.

- All 13 Robot Shop, five voting, and five observability workloads stayed Ready.
- Purchases increased from 40,737 to 43,234: **2,497 completed purchases**.
- Maximum sampled load memory was 54,525,952 bytes (52 MiB); the last ten
  samples ranged from 33 to 39 MiB.
- The 34 clean five-minute traffic windows averaged 1.574706 requests/second,
  about 4.8% below the earlier 1.654444 reference, with zero recorded HTTP
  errors. The mixed V2/V3 warm-up window is excluded. This is comparable live
  traffic, not a claim of identical timing for a random workload.
- The independent `23:10Z` recheck found the same pod running for over six
  hours with zero restarts. Kernel cgroup peak was 68,870,144 bytes (65.7 MiB);
  `memory.events` reported `max=0`, `oom=0`, and `oom_kill=0`.
- Resource limits remained **200m CPU / 256 MiB memory**, and the Redis PVC UID
  was unchanged: `d294287d-b728-46a5-bb83-fd7dc694234e`.
- The final ConfigMap source SHA-256 remained
  `0058b06048c63d083918e172ac92275c4e41207b69e32516289f21e974987986`.

Raw aggregate samples and summary remain on EC2 in
`/tmp/ts-load-oom-fix/soak-20261023T163215Z`. This verifies the measured OOM
fix under the unchanged course workload; it does not promise unlimited
stability or replace the instructor incident drill. Historical checkpoints
and the superseded V2 result are retained below.

## V3 Early Traffic Checkpoint

At `2026-10-23T16:37:34Z`, the first clean five-minute window after the V3
rollout recorded 490 requests, zero HTTP errors and 1.633333 requests/second.
The pre-fix 15-minute reference was 1.654444 requests/second, so this initial
window was within about 1.3% of the reference. This is an early comparison,
not a guarantee that every random five-minute window must match exactly.

The first 11 soak samples had no failures, the same V3 pod UID, zero restarts,
13/5/5 Ready workloads, and a latest sampled load memory of 34,603,008 bytes
(33 MiB). `sold_count_total` increased by 72 over those samples.

This early checkpoint was provisional. The final acceptance result is above;
the superseded V2 observations are not part of that pass.

## Classification

The prior `load` failure was a **container limit reached** event, not node
limit overcommit. The 256 MiB load cgroup reached its limit and Kubernetes
reported `OOMKilled` / exit 137 while the node retained free capacity.

## V2 Change and Gates (Historical)

The standalone load generator retains its pinned image, 200m CPU limit, 256 MiB
memory limit, two users, endpoints, payloads, waits, and country selection.
Only the shipping city response reader changed: it streams UTF-8 JSON, keeps
one bounded city record, and reservoir-samples the full array. The script also
performs a cooperative hourly Locust reporting-state reset.

The source hash is
`09f1a89b7b4fd050a02ebdfd2bbf4bb4d7c6834bfbe730c588bfc4d8276a4ea4`.
Helm lint, rendered-manifest validation, Kubernetes server dry-runs, the
no-network route-cardinality check, and the city stream fixtures passed on
EC2 before rollout. Robot Shop Helm revision 3 updated the script ConfigMap;
the separate standalone Deployment was then applied.

The prior exact-image comparison at the unchanged 256 MiB / 0.2 CPU budget
peaked near 248 MiB using the materializing path and near 49 MiB with the
streaming path. The rare large-country request can take longer on the fixed
CPU budget, so live RPS comparability is a manual before/after evidence review,
not an assumed pass condition.

## V2 runtime result: superseded for performance

- New pod: `load-79ddcf5b78-kqcjp`
- Pod UID: `225ef08b-6dd7-4b72-976b-1ee49ee243e1`
- Created: `2026-10-23T16:04:17Z`
- Mounted ConfigMap and in-container source hashes match the reviewed hash.
- At soak start: Robot Shop 13/13, Voting 5/5, observability 5/5 Ready;
  load restarts 0; Redis PVC UID unchanged
  (`d294287d-b728-46a5-bb83-fd7dc694234e`).
- Transient unit: `ts-load-oom-soak-20261023T161700Z.service`
- Output: `/tmp/ts-load-oom-fix/soak-20261023T161700Z`
- Started: `2026-10-23T16:17:00Z`; stopped at `2026-10-23T16:27Z` after
  preliminary throughput evidence showed an unacceptable regression.

The sampler takes 30-second aggregate samples only. It gates on the stable pod
UID/restart count, health counts, memory at or below 128 MiB, a recent memory
plateau, increasing purchases, and positive five-minute web RPS. The first
recorded samples had no failures; one early sample at `2026-10-23T16:17:33Z`
reported 34,603,008 bytes of load memory, zero restarts, 13/5/5 Ready, and
`sold_count_total` 40,682.

The initial v2 sampler was intentionally stopped rather than allowed to claim
a soak pass. It preserved 21 JSONL samples in
`/tmp/ts-load-oom-fix/soak-20261023T161700Z`. Memory remained approximately
33-38 MiB (kernel cgroup peak 40,448,000 bytes), with zero load restarts and
no sampled errors. However, observed five-minute web RPS was materially below
the pre-change baseline (about 1.654 RPS); early windows included roughly
0.67 and 0.63 RPS, and a later window was 0.183 RPS. This is a **performance
supersession**, not an OOM regression.

The container retained the unchanged 0.2 CPU limit (`cpu.max 20000 100000`).
At capture, `cpu.stat` reported 10,424 periods, 9,495 throttled periods, and
682,530,512 throttled microseconds. The likely avoidable source of the RPS
loss is the Python character-by-character JSON framing loop under that fixed
CPU budget. A reviewed v3 bounded raw-decoder fast path is required before a
new controlled rollout and a fresh full soak clock.

## V3 Runtime Soak Setup (Historical)

The focused raw-decoder fast path passed review and exact-image checks without
changing the image, 0.2 CPU limit, 256 MiB memory limit, users, wait times, or
traffic profile. For the two-client representative 18 MiB test, the original
materializing reader completed in about 9.4 seconds but peaked near 248 MiB;
v2 completed in about 46.3 seconds at about 49 MiB. V3 completed in 20.197
seconds with a 46,354,432-byte (under 45 MiB) cgroup peak.

Helm revision 4 changed only `robot-shop-load-script` ConfigMap data; the
standalone load Deployment then changed its script-version annotation to v3.
The fresh pod is `load-5855488db7-4s868`, UID
`47cb54ab-a575-46ae-a45e-8365a8c9411a`, created `2026-10-23T16:31:41Z`,
with zero restarts. Its ConfigMap and mounted source hash are
`0058b06048c63d083918e172ac92275c4e41207b69e32516289f21e974987986`.
Robot Shop, Voting, and observability were 13/13, 5/5, and 5/5 Ready; the
Redis PVC UID remained unchanged.

The fresh owned transient soak is
`ts-load-oom-soak-20261023T163215Z.service`, writing to
`/tmp/ts-load-oom-fix/soak-20261023T163215Z`, from `2026-10-23T16:32:15Z`
until `2026-10-23T19:32:15Z`. The first five-minute web-RPS window includes
v2 tail traffic and is warm-up evidence only. Compare windows at or after
`2026-10-23T16:36:41Z`, preferably after fifteen minutes, against the
pre-v2 baseline of approximately 1.654 RPS. The full summary subsequently
passed as recorded above.

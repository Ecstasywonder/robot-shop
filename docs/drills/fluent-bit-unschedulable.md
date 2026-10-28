# Fluent Bit unschedulable simulation

**Classification:** recovered, passing student-led controlled simulation. It is
not an instructor-led drill.

## Run record

- Run ID: `20261028-logging-loss-01`
- Baseline: `2026-10-28T13:20:52Z`; a fresh check recorded 10 healthy inactive
  rules and 27 Ready workloads, including routing recovery.
- Injection: `2026-10-28T13:20:53Z`; Fluent Bit generation `4` was injected
  with the approved unschedulable condition.
- Safeguards: 480-second independent rollback guard and 1,800-second observer
  at 30-second intervals.

`FluentBitRedMetricsUnavailable` was pending at `13:22:00Z` and firing at
`13:26:56Z`. `CartGatewayTrafficAbsent` was pending only and never fired.
Alertmanager recorded Slack-success rate-window increase `1.1111111111111112`
with failure increase `0` at `13:27:29Z` while the Fluent Bit alert was firing;
this is neither an integer delivery count nor human acknowledgement. The
watchdog restore attempt was at `13:28:53Z`, restored state at `13:28:54Z`, and
all alerts were cleared at `13:29:40Z`.

The observer recorded one baseline and 48 samples (49 JSONL lines); its final
sample at `13:46:43Z` was 17 minutes 49 seconds after restoration. Every sample
recorded `critical=[]`. The final sample had positive RED traffic for all four
services with no error series (request-conditioned zero), payment 2xx rate
`0.07778/s`, and 23 spans. At `13:24:12Z`, while Fluent Bit was unscheduled,
independent GETs to the web root and Catalogue products proxy succeeded
(`2891` and `2196` bytes; bodies were not retained); this does not prove the
gateway checkout path.

At `13:43:02Z`, replacement Pod `fluent-bit-w4hwm` (UID
`f0c7ef38-6ce4-49c1-a5bc-f424e79d4ada`) was Ready with zero restarts; its node
selector was absent and desiredReady was one. A Loki query 30 seconds after
restore returned five fresh web entries, latest timestamp
`1793194981462657690`. At `13:46:42Z`, both scrape endpoints had
`min_over_time(up[15m]) = 1` with 30 samples each. Fluent Bit tail DB/buffer
reset means a collection gap or loss remains possible; this run claims neither
uninterrupted collection nor replay. The
[canonical archive](../evidence/drills/20261028-logging-loss-01/) includes
the independent service checks and fresh-log recovery verification.

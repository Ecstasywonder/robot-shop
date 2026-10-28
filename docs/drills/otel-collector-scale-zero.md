# OpenTelemetry Collector scale-to-zero simulation

**Classification:** recovered, passing student-led controlled simulation. It is
not an instructor-led drill.

## Run record

- Run ID: `20261028-tracing-loss-01`
- Baseline: `2026-10-28T13:47:52Z`.
- Injection: `13:47:54Z`; Collector replicas changed `1` → `0`.
- Alert: `PaymentTraceCollectorUnavailable` pending at `13:48:28Z`, firing at
  `13:50:40Z` with `service=payment-tracing`.
- Safeguard: watchdog restore attempted at `13:51:54Z`; restored state at
  `13:51:55Z`.

Alertmanager recorded Slack-success rate-window increase `1.111` with failure
increase `0` at `13:51:13Z` while the alert was firing. This is not an integer
delivery count or evidence of human acknowledgement.

During the outage after the 30-second settle period (`13:48:24Z`–`13:51:21Z`),
Loki counted 13 payment-gateway HTTP 200 events, with timestamps
`1793195343820183277` through `1793195466884108543`. Six valid Jaeger samples
were existing traces, whose latest start (`1793195273479760303`) preceded the
injection; no new spans were observed after settling. Only counts and timestamps
are recorded, not trace IDs or log lines.

At `13:53:21Z`, one Collector was available: Pod
`otel-collector-7bf65f9984-wpl7w` (UID
`44354f47-8f46-44f8-9a36-451db648f37a`) was Ready with zero restarts. The first
post-restore fresh span started at `13:52:11.546Z`
(`1793195531546737115`) and was observed at `13:52:19Z`, alongside payment 2xx
rate `0.09259`; this distinguishes a new span from a buffered old trace.
`critical=[]` held through that observation.

## Recovery closure

The observer recorded one baseline and 47 samples (48 JSONL lines). Its last
sample at `14:12:55Z` was 21 minutes after restoration and 20 minutes 03
seconds after alert clearance. Every sample recorded `critical=[]`; the final
payment 2xx rate was `0.074074/s`, 23 spans were present (latest start
`1793196771565656122`), and RED error series were absent while requests were
positive. At `14:20:08Z`, Collector availability had minimum one across the
last 15 minutes with 30 KSM samples; the Collector Pod retained its UID with
zero restarts and fresh span/payment evidence remained present. The observer
naturally completed its 1,500-second window and its unit was garbage-collected;
an operator stop reporting `not loaded` was normal completion, not failure.
This is a recovered, passing student-led simulation. Its
[canonical archive](../evidence/drills/20261028-tracing-loss-01/) includes
the outage and post-restoration verification records.

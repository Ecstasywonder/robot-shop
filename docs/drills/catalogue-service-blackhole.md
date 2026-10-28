# Catalogue Service black-hole simulation

**Classification:** recovered, passing student-led controlled simulation. It is
not an instructor-led drill.

## Run record

- Run ID: `20261028-catalogue-routing-01`
- Baseline: `12:58:41Z`; 10 healthy inactive rules and 27 Ready workloads.
- Injection: `12:58:42Z`; the first Catalogue Service HTTP/TCP port target
  changed `8080` → `65000`.
- Safeguards: 300-second independent rollback guard and a 1,500-second observer
  at 30-second intervals.

## Observed recovery

All strict-baseline Pods remained Ready and unchanged with zero restarts at the
sampled checks; every sample recorded `critical=[]`. `Gateway5xxRule` was
pending at `13:00:22Z` and firing at `13:02:01Z` with `service=catalogue`.
Alertmanager recorded Slack-success rate-window increase `1.1111111111111112`
with failure increase `0` at `13:03:07Z` and `13:03:40Z` while the alert was
firing. Those values are rate-window measurements, not integer delivery counts
or human acknowledgement.

The independent watchdog attempted restore at `13:03:42Z` and recorded restored
state at `13:03:43Z`, with the Service field returned to `8080`. At `13:05:19Z`,
the record contained one baseline plus 13 samples (14 JSONL lines),
`critical=[]`, payment 2xx rate `0.02963`, and 10 fresh-window spans, indicating
request recovery. `Gateway5xxRule` remained firing as expected within its
rolling five-minute window; Catalogue error rate was `0.1481`.

## Recovery closure

The alert first cleared at `13:08:04Z`. The observer recorded one baseline and
40 samples (41 JSONL lines); its final sample at `13:20:07Z` was 16 minutes 24
seconds after restored state. Every sample recorded `critical=[]`. The final
sample had no Prometheus or Alertmanager alerts, zero web/payment/Cart/Catalogue
RED error rates, positive Catalogue request rate `0.4296/s`, payment 2xx rate
`0.1037/s`, 32 spans, and zero Slack failures. The
[canonical archive](../evidence/drills/20261028-catalogue-routing-01/)
contains the completed evidence. This is a recovered, passing student-led simulation.

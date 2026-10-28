# Cart Gateway Availability SLO and Error Budget

## Objective

The Cart gateway has a request-based availability objective of **99% over a
rolling 24 hours**. An eligible request is a valid HTTP access event emitted by
the Robot Shop `web` gateway with `target_service="cart"`, normalized by Fluent
Bit into `robotshop_http_requests_total{namespace="log-collection",service="cart"}`. A request is
successful when it is not a 5xx response; a 5xx increments
`robotshop_http_errors_total{namespace="log-collection",service="cart"}`. This measures customer-facing
gateway behavior, not the internal Cart process, a health endpoint, or a raw
container restart count.

The 24-hour compliance query is:

```promql
1 - (
  sum(increase(robotshop_http_errors_total{namespace="log-collection",service="cart"}[24h]))
  or on() (sum(increase(robotshop_http_requests_total{namespace="log-collection",service="cart"}[24h])) * 0)
) / sum(increase(robotshop_http_requests_total{namespace="log-collection",service="cart"}[24h]))
```

The `or ... * 0` fallback represents a valid zero-error period when request
data exists but no 5xx counter has yet been emitted. It is not a fallback for
missing request data. If the request denominator is absent or zero, the result
is no data and the SLO is **unknown**, never 100% availability. Likewise,
collection is unknown when the Fluent Bit RED-metrics target is unavailable;
the companion alert must be resolved before interpreting this query. The metric
data is collected every 30 seconds and Prometheus retains three days, so the
full 24-hour objective is evaluable only after 24 hours of continuous healthy
collection. This policy does not retroactively certify availability before that
data exists.

The 25–26 October student-led Cart drills found that gateway 5xx responses
were attributed to `web`, so the Cart-specific ratio missed observed outages.
Those affected windows cannot establish Cart SLO compliance, even if this
query returns a high value. A corrected attribution path must pass a live
fault test before a new, trustworthy 24-hour window begins. See the
[Cart simulation record](drills/cart-scale-zero.md).

## Error Budget

The 99% objective permits **1% failed eligible cart requests** in each rolling
24-hour window. The budget is counted in requests, not minutes: for example,
10,000 eligible requests allow 100 5xx responses. Any unavailable or
unobserved requests are not silently added to either numerator or denominator;
they require telemetry investigation first.

`CartGatewayAvailabilityDegraded` is a short-window SLO-breach warning: it
fires only when there are at least 20 cart requests, the 5xx ratio exceeds 1%,
and the condition persists for two minutes. It is not a multi-window burn-rate
alert and does not replace the 24-hour SLO calculation.

## Response Policy

When the availability-degraded alert fires, follow the linked Cart runbook: mitigate
customer impact first, preserve evidence, then identify contributing causes.
Pause non-essential Cart changes while the budget is consumed. Escalate an
incident when the impact persists or the 24-hour budget is exhausted; do not
declare recovery until the customer path and telemetry both recover. Document
the drill or incident separately in a blameless postmortem. The current
load-generator OOM investigation is a separate capacity/stability event and is
not represented as the instructor-required incident drill.

The course supplied no SLO template, so this is an equivalent, authored
one-page policy based on the stated availability, error-budget, Slack-alert,
and runbook requirements.

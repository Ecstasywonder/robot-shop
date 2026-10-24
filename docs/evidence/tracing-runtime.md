# Payment Tracing Runtime Evidence

Date: 24 October 2026 (Africa/Lagos).

## Private Deployment

- Applied the reviewed tracing Kustomization: two non-public `ClusterIP`
  services, `otel-collector` on OTLP/HTTP 4318 and Jaeger on OTLP/gRPC 4317
  plus its private UI/query port 16686.
- Both trace deployments became Ready with zero restarts. Their ConfigMaps are
  content-hashed by Kustomize and the exact rendered bytes passed the project
  checker plus the pinned Collector and Jaeger config validation before apply.
- The payment egress policy permits only its reviewed dependencies, DNS, and
  the Collector. The Collector can send only to DNS and Jaeger. Existing broad
  same-namespace observability access remains a documented educational
  residual; no service was exposed publicly.

## Payment Rollout

Robot Shop Helm revision 5 enabled tracing only for payment, with
rollback-on-failure and readiness waiting. The payment pod is
`payment-6b8fb75ff-c24j5` (UID
`580f1c73-67ec-46f0-b399-d8b1805e4caa`) and uses the EC2-built,
cluster-local immutable image:

`ts-academy/rs-payment-otel@sha256:423ae2c970248b2a4b6be50ba0992bbe434d57b2abb7b7f8bcaa5b4e8ad3f39a`.

The image's source hashes matched the canonical payment source before import.
`OTEL_TRACING_ENABLED` and the private OTLP endpoint are present. The original
payment budget remains 200m CPU / 100 MiB memory (50m / 50 MiB requests).
At the final check it used 3m CPU and 35 MiB memory, with zero restarts.

## Trace Proof

The existing synthetic load was allowed to drive normal internal traffic; no
real payment was initiated and no service fault was injected. A temporary
operator-only port-forward to the private Jaeger service was opened and
cleaned up after each query. Jaeger's stable v3 query API returned `payment`
as a service and `payment.pay` as its operation. A bounded 15-minute query
found 20 `payment.pay` spans; only the first 12 hex characters of one trace ID
(`ada3f6c7c1af`) were retained as evidence. No user ID, cart content, URL,
header, request body, exception message, or trace payload was recorded.

## Final Health

At the final check, all 13 Robot Shop pods, five voting pods, eight
observability pods (including Collector and Jaeger), and one Fluent Bit pod
were Ready with zero restarts. This verifies the course requirement for one
OpenTelemetry-instrumented service and one trace visible in Jaeger. It does
not make the ephemeral, in-memory Jaeger store durable or turn its private
plaintext OTLP hop into a production confidentiality boundary.

## Post-Rollout Operating Check

After the initial trace proof, a separate read-only two-minute observation
queried payment's existing local `sold_count_total` metric at two points. It
increased from 138 to 160: **22 completed purchases**. The payment pod UID
remained `580f1c73-67ec-46f0-b399-d8b1805e4caa` with zero restarts.

At the same check, payment's cgroup reported 38,535,168 bytes current memory
and a 43,442,176-byte peak. `memory.events` had zero `low`, `high`, `max`,
`oom`, `oom_kill`, and `oom_group_kill` counters. All 13 Robot Shop, five
voting, eight observability, and one Fluent Bit pods were Ready with zero
restarts. This confirms that the tracing rollout did not interrupt the observed
synthetic checkout stream during this bounded window; it is not a claim of
unlimited future capacity.

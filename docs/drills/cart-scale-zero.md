# Cart scale-to-zero student-led simulation

**Classification:** student-led controlled simulation. This was not an
instructor-led incident drill, and TS Academy has not yet decided whether it
can satisfy an instructor-led requirement.

## Record

- Run ID: `20261025-cart-01`
- Injection time: `2026-10-25T18:32:01Z`
- Runner and observer identifiers used for this run: `6cba858` and `72f5d141`,
  respectively. These are distinct from the newer versions approved for future
  simulations.
- Injected condition: `robot-shop/cart` Deployment replicas changed from the
  reviewed baseline of `1` to `0`.
- Baseline: 27 project workloads Ready and zero restarts.
- Scope: the Cart Deployment desired replica count only. No database, PVC,
  queue, node, control-plane, public endpoint, security group, or secret was
  changed.

## Observed timeline

| UTC time | Observation or action | Result |
| --- | --- | --- |
| `18:32:01` | Guarded runner injected the declared replicas `1` → `0` mutation. | Simulation began. |
| `18:34:19` | Prometheus observed `RobotShopGateway5xxRateHigh` as pending for `service=web`. | The gateway had one `504` and 36 `502` responses, both attributed to `web`. |
| `18:36:25` | Alertmanager reported the generic alert active. | Slack notification success increase was `1.111` (a rate-window extrapolation, not an integer delivery count); notification failure was `0`. |
| `18:37:21` | Scoped runner restore attempted the guarded Cart replicas restore. | Fault duration was 320 seconds. |
| By approximately `18:38:33` | A replacement Cart Pod became Ready with zero restarts. | The observer recorded `critical=[]`; unrelated original Pod UIDs were preserved. |
| `18:39:09` | Recovery observation sampled the customer path and counters. | `critical=[]`; payment 2xx rate was `0.02963`, with item/accounting counters increasing. The generic 5xx alert remained firing within its rolling five-minute evaluation window. |

## Alert coverage finding

The Cart-specific alert did not fire during this simulation. Nginx's internal
`error_page` redirect to `/50x.html` changed the `$uri` used by the access-log
map, so failed Cart requests were attributed to `service=web`. The generic
gateway 5xx alert therefore observed the customer-facing failure, while no Cart
error series existed for the scoped alert.

This is a monitoring-coverage gap, not evidence that Cart was healthy. A
corrective Nginx/metric-mapping change was verified in an isolated EC2 Nginx
regression and deployed in Robot Shop Helm revision 6 at
`2026-10-25T18:54:49Z`. It maps the original request URI without emitting that
URI in structured logs; forced 502 responses for Cart, Catalogue, and Payment
kept their respective target-service labels. The following live retest showed
that this single-leading-slash fixture did not reproduce the load generator's
actual request form.

## Distinct live retest

The retest is a separate student-led controlled simulation. It does not change
the evidence or conclusions of the first Cart run.

- Run ID: `20261026-cart-retest-01`
- Injection time: `2026-10-26T18:47:01Z`
- Guarded restore time: `2026-10-26T18:51:16Z`
- Fault duration: 255 seconds

Despite the deployed Helm revision 6 template and its isolated EC2 regression,
the live error metric was again labeled `service=web`. The Cart-specific alert
did not fire. `RobotShopGateway5xxRateHigh` fired for the gateway impact, and
Alertmanager recorded Slack success increase `1.111` (a rate-window
extrapolation, not an integer delivery count) with zero delivery failures.

The exact deployed-image reproduction ruled out an Nginx 1.20.1-versus-1.28
version difference. A single `/api/cart` 502 is correctly labeled with the
revision 6 `$request_uri` map; a `//api/cart` 502 is labeled `web`. The Locust
host is `http://web:8080/` and its request prefix is `/api/cart/...`, producing
that double-leading-slash form. Nginx normalizes it for location matching and
upstream routing, but preserves `//api/...` in `$request_uri`, so the
single-slash regex does not match. The earlier `$uri` map was also unsafe for
error-page redirects, but that was only part of the live root cause.

A second correction has passed an exact deployed-image regression: accept one
or more leading slashes before `api` while retaining the route boundary check.
The candidate template SHA-256 is
`14547bcc3ebf302b52d61a76d17dfc03f238fcaebb18cf96845dcf0b23406e12` and
its test SHA-256 is
`144db3112b745d8031120d1f07878dfe7040b5bce0d00ad2e85c581415a4ecbc`.
The EC2 fixture passed single- and double-leading-slash 200/502 checks for
Cart, Catalogue, and Payment, including end-of-path and query boundaries. It
also confirmed structured logs omit URI, request, and header fields; temporary
fixtures were removed. The candidate deployed as Robot Shop Helm revision 7 at
`2026-10-26T19:11:46Z`, rolling only the web workload. The mounted map was
verified as `^/+api`, and workloads had settled before the next test.

## Historical first and second attempts

The first two student-led Cart attempts recovered their workloads but only the
generic gateway alert was attributed to `service=web`; neither met the scoped
Cart-alert objective. The first archive has one baseline plus 41 samples (42
JSONL lines), with final healthy observation at `2026-10-25T18:53:54Z` and a
separate `18:54:25Z` health check showing payment 2xx rate `0.0667` and zero
Slack failures. The second archive has one baseline plus 38 samples (39 JSONL
lines), with final healthy observation at `2026-10-26T19:06:44Z`, zero RED
errors, and 26 payment spans. The timer-cleanup anomaly was closed by a
baseline-only frozen watchdog returning `already_restored` with zero loaded
drill units; no baseline workload was changed.

## Third live retest: scoped-alert objective passed

The third, separate student-led controlled simulation is closed.

- Run ID: `20261026-cart-retest-02`
- Baseline recorded: `2026-10-26T19:13:46Z`
- Injection: `2026-10-26T19:13:47Z`
- Alert pending: `2026-10-26T19:15:27Z`
- `CartGatewayAvailabilityDegraded` firing: `2026-10-26T19:17:05Z`, with
  `service=cart`
- Independent watchdog restore attempt: `2026-10-26T19:19:47Z`; terminal
  restored state: `19:19:48Z`
- Alert cleared: `2026-10-26T19:24:44Z`
- Last observer sample: `2026-10-26T19:43:48Z`

The fault, including restored-state confirmation, lasted 361 seconds. The raw
observer record has one baseline plus 56 sample events (57 JSONL lines). The
last sample was 24 minutes after rollback and 19 minutes after alert clearance;
it recorded `critical=[]`, no active alerts, zero RED errors, 25 payment spans,
and payment 2xx rate `0.07037`. Slack notification failures remained zero.
Alertmanager recorded Slack notification delivery-success rate-window increases
of `1.1111111111111112` with failure increase `0` at both `19:17:38Z` and
`19:18:10Z`, while `CartGatewayAvailabilityDegraded` was firing for
`service=cart`. The same success increase and zero failure were present in the
later resolved windows at `19:31:18Z` and `19:31:51Z`. These are rate-window
measurements, not integer delivery counts or evidence of human acknowledgement.

The verified scope of the Nginx fix is the exact deployed `rs-web` Nginx 1.20
image regression: Cart, Catalogue, and Payment single- and double-leading-slash
paths returned the expected 200/502 outcomes; end-of-path and query boundaries
returned 301 as expected; URI, request, and header fields were absent from the
structured-log fixture; and temporary fixtures were cleaned up. The deployed
template SHA-256 is
`14547bcc3ebf302b52d61a76d17dfc03f238fcaebb18cf96845dcf0b23406e12`.

As of the independent verification on `2026-10-28T12:01Z`, all 27 workloads
were Ready with zero restarts, no drill units were active, and this run's state
was `restored`. The canonical archive is stored on EC2 at
`docs/evidence/drills/20261026-cart-retest-02/` and contains safe JSON baseline,
samples, audit, and state records. It has not yet been synchronized into this
local checkout.

The initiating condition was intentionally injected for this simulation. This
record names no individual cause or fault; it documents system behavior and
the evidence needed to improve the service.

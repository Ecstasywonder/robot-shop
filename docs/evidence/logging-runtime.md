# Robot Shop Logging Runtime Evidence

Date: 2026-10-24 (Africa/Lagos)

## Collector and Loki

- Helm release `loki` remains revision 1 in `observability`, with its private
  `ClusterIP` service on port 3100 and the existing 4 GiB local-path PVC.
- Fluent Bit is revision 3 in `log-collection`. The parser correction replaced
  only the DaemonSet pod: `fluent-bit-5ls9c` (UID
  `56f8d485-3061-4961-aaa4-4a5632e0bb6c`) became Ready with zero restarts.
- The pinned chart (`fluent-bit` 0.58.3) passed lint, client rendering, and
  server-side dry run before the Helm 4 rollback-protected rollout. Rendering
  contains no `ClusterRole` or `ClusterRoleBinding`.

## Safe JSON Normalization

CRI parsing places application output in `message`. The collector renames that
field to `log`, then has the Kubernetes filter decode it under the nested
`app` key (`Merge_Log_Key app`). Lua reads trusted Kubernetes metadata only
from the top level and validates the nested application fields before exposing
the bounded RED dimensions. Thus application JSON cannot forge the collector's
Kubernetes `container_name` or `labels.service` metadata.

`observability/logging/test-normalize-contract.sh` ran on the EC2 workstation
against the pinned Fluent Bit image. Its adversarial `app.kubernetes` record
did not replace the trusted metadata; a valid 5xx access record became RED
eligible, and an ordinary non-JSON `ERROR` line still became `level=error`.

## Live Query Gates

- The collector endpoint emitted request counters and duration histograms for
  `web`, `catalogue`, `cart`, and `payment`; Prometheus observed them with the
  application `service` label and `namespace="log-collection"` from the
  Fluent Bit scrape target.
- The healthy traffic window had no 5xx counter series. The dashboard's
  request-conditioned zero-error fallback evaluated to exactly `0`; it does
  not invent a value when requests are absent.
- A 120-second, non-privileged, tokenless BusyBox pod with
  `service=capstone-log-check` emitted one fixed, harmless error-level line
  after tail discovery. Loki query `{service="capstone-log-check",level="error"}`
  returned one stream and one entry. The pod UID
  `b1dd723c-87df-4345-bec9-67cf0386a9ba` was verified before deletion. This is
  a synthetic logging-pipeline check, not an application fault or the required
  instructor-led incident drill.

The earlier NetworkPolicy proof remains valid: DNS, Kubernetes API, and Loki
were allowed for the logging flow, while Prometheus and public internet egress
were denied. No raw log records, request payloads, or credentials are included
in this evidence.

## Positive-Control Independence

`check-network.py` no longer uses the live payment pod as the internet
positive control. Before the tracing policy restricts payment egress, the
script now creates a separate hardened pod in `robot-shop` with a unique label
outside all application and controller selectors. It uses the same cached,
digest-pinned Python image, has no service-account token and bounded
resources, verifies `example.org:443`, then UID-guards its own cleanup. This
keeps the logging policy proof independent of the payment policy. The revised
script compiled and passed on the EC2 cluster; both its control pod and its
logging probe were absent after completion, while Fluent Bit remained Ready
with zero restarts.

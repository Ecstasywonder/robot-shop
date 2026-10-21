# Robot Shop healthy baseline

Verified on 21 October 2026 on the existing Terraform-managed EC2 K3s cluster.
All downloads, rendering, installation, and runtime checks ran on EC2.

## Source and preflight

- Personal fork: https://github.com/Ecstasywonder/robot-shop.
- Original source: `55292e2199f2fb00a165b1f7d3045fe7f8922038`.
- Applied source patch SHA-256:
  `9ad9a46f4edf67aea969db8a7addae62353cd60192f4468ff19cd7d9054d44de`.
- Exact patch passed normal `git apply --check` before application.
- Helm lint: one chart checked, zero failures.
- Validator fixtures: accepted safe input, rejected 15 unsafe variants.
- Structured render gate: `true`, 25 objects, 13 workloads/containers, all
  namespaced to `robot-shop`. Redis creates its PVC through volumeClaimTemplates.
- Server-side dry runs passed after creating the namespace and its ingress policy.

The initial preflight caught two operator-pipeline errors, neither deployed:
client dry-run without an explicit namespace used `default`, and directly
concatenating YAML without a separator replaced the final Redis document with
the load manifest. The corrected procedure uses separate `-f` inputs, an explicit
namespace, and normalized JSON. The safety validator was not weakened.

## Runtime acceptance

Helm release `robot-shop`, namespace `robot-shop`, revision 1: `deployed`.
Load was started only after all 12 application pods became Ready.

At `2026-10-21T07:49:02Z`:

- All 13 pods Ready: cart, catalogue, dispatch, mongodb, mysql, payment,
  rabbitmq, ratings, redis, shipping, user, web, and load.
- All 12 services ClusterIP; zero public service types.
- Redis claim `data-redis-0`: Bound, 1 GiB, storage class `local-path`.
- Zero pod service-account-token automount violations.
- Zero Instana/EUM environment-setting violations.
- No active Instana/OpenTracing directives in web's runtime Nginx configuration.
- Payment gateway: `http://web:8080/`, an internal HTTP-200 stub, not PayPal.
- Voting application remained 5/5 Ready before and after this rollout.

The payment `/metrics` endpoint proved real checkout activity:

| UTC time | `sold_count_total` |
| --- | ---: |
| 07:50:23 | 28 |
| 07:52:08 | 50 |

Increase: 22 completed purchases in 105 seconds. The payment pod did not restart
during this sample. Load uses two clients continuously, with deliberate error
injection disabled. These results establish functional traffic, not a throughput
benchmark or an SLO measurement window.

## Scope and residual risks

Private ingress allows only same-namespace pods; no egress isolation is claimed.
Images are digest-pinned, but the upstream application is an older educational
demo with permissive database authentication and root/default-capability
containers. Baked optional tracing libraries have not all been removed.
The namespace enforces Baseline PSS v1.36; Restricted findings are warnings and
audit events. This is not a production-security endorsement.

Metrics, log collection, tracing, Slack alert delivery, and the incident drill
are separate acceptance gates. Source publication to the personal fork remains
pending at the time of this baseline record.

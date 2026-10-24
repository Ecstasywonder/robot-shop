# Robot Shop memory stability

The observed `load` failure is a container cgroup limit event, not node memory
overcommit: the 256 MiB `load` container reached its limit and was terminated
with `OOMKilled` / exit 137 while the Kubernetes node retained available memory.

The load script now reads the shipping city array incrementally, validates one
bounded city object at a time, and uses reservoir sampling. It preserves the
same endpoints, payloads, wait times, users, country selection, and 256 MiB
limit. An hourly cooperative Locust statistics reset bounds reporting state for
the unlimited run. In an EC2 exact-image comparison with two clients and an
18 MiB Unicode city feed, the reviewed V3 implementation peaked under 45 MiB;
the prior materializing implementation peaked near 248 MiB.

The rollout does not change the pinned load image, CPU/memory limits, service
topology, or traffic profile. Runtime acceptance requires a fresh pod UID with
zero restarts, all Robot Shop, Voting, and observability pods healthy, stable
load memory below 128 MiB, and increasing purchase totals during the soak.

V3 passed that three-hour gate with 340 samples, zero restarts, 2,497 additional
purchases, and a 52 MiB maximum sampled load footprint. A later independent
check found the same pod healthy after over six hours, with zero kernel OOM
events and a 65.7 MiB cgroup peak. See [the rollout evidence](evidence/load-oom-fix.md)
for exact identities, resource limits, and the historical V2 performance result.

`deploy/check-load-soak.py` is the frozen acceptance sampler for that baseline:
it expects 13 Robot Shop, five voting, and five observability pods. Additional
logging/tracing components change those counts. Do not rerun it unchanged as
an ongoing cluster monitor; use the current runbook and scoped Prometheus
rules, or review and explicitly revise the acceptance baseline first.

Shipping uses an explicit bounded JVM heap (`-Xmn128m -Xmx512m`) inside its
existing 1000 MiB limit. It must be independently observed; its diagnostic
`/memory` endpoint remains a separate potential failure mechanism.

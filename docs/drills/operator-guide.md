# Incident-drill runner operator guide

## Approval state

**GO for future controlled simulations:** runner SHA-256
`eece29c28b43f7471cbded3840003e2601c880641860a4a653fd18cb739230c9`
and observer SHA-256
`d2cdfe3f8b4f7c36056db73c0e535cc30a07856855cee32a399a35992491c6fb`
(reviewed 28 October 2026). This approval covers the fixed, allowlisted
workflow and its documented hard limits. It does not authorize a new drill
when the preflight, observer, or recovery checks are unhealthy.

Validation recorded for these versions: 29 runner tests, including two real
systemd checks, and 14 observer tests, including RFC 3339 timestamp coverage,
passed on EC2. The earlier Cart run keeps its own recorded runner and observer
hashes; do not substitute these newer versions into that evidence.

The runner must execute as root on the cluster host. It never copies a private
key, agent credential, kubeconfig, or secret. Its only cluster client is the
cluster host's `/usr/local/bin/k3s kubectl`.

## Fixed safety envelope

Only these cases exist; the CLI cannot provide a namespace, resource, path,
value, or duration.

| Drill | Atomic owned mutation | Hard limit |
|---|---|---:|
| `cart-scale-zero` | `robot-shop` Deployment `cart`: explicit replicas `1` → `0` | 6 min |
| `catalogue-crashloop` | `robot-shop` Deployment `catalogue`, container `catalogue`: absent command + absent readiness probe → `['/bin/sh','-c','exit 42']` + failing TCP/8080 probe | 4 min |
| `catalogue-service-blackhole` | `robot-shop` Service `catalogue`, first port exactly `http:8080/TCP`: targetPort `8080` → `65000` | 5 min |
| `fluent-bit-unschedulable` | `log-collection` DaemonSet `fluent-bit`: absent nodeSelector → impossible selector | 8 min |
| `otel-collector-scale-zero` | `observability` Deployment `otel-collector`: explicit replicas `1` → `0` | 4 min |

The catalogue command and readiness probe are one two-field JSON Patch and one
restore patch. The probe prevents a one-replica RollingUpdate (`25%` surge,
`25%` unavailable) from treating the injected replacement as Ready while the
old pod is retained. The full API-stored probe value is owned and compared
exactly.

No drill changes a database, PVC, queue, node, control plane, public port,
security group, or infrastructure. Fluent Bit container logs backed by
`emptyDir` can have a collection gap or be lost when a pod is replaced; record
that limitation in the drill evidence.

## Safety model

`prepare` requires the exact approved baseline, records UID, resourceVersion,
generation (including absence), resource identity, and field-presence
semantics. It creates a root-owned `0700` run directory beneath the root-owned
`0700` `/var/lib/ts-capstone-incident-drills` base and freezes a root-owned
`0500` runner copy. Base, child, runner, state, audit, and lock access uses
non-following file-descriptor operations and verifies owner, type, mode, and
inode where applicable. A pre-created symlink or permissive path is fatal.

`start` refuses any drift since `prepare`. Before mutation it arms and verifies
an independent systemd timer. The timer launches only the frozen runner and
uses `Restart=on-failure`, a 10-second retry interval, and unlimited start
attempts. Both kubectl's API request and its local process have timeouts. The
global lock is nonblocking, so a watchdog attempt never waits behind a stalled
operation; it exits and systemd retries. A timer-arm or verification failure
causes no mutation. An unknown patch outcome is persisted as
`mutation_unknown`, with the watchdog left active.

Every restore attempt reads the live object again. Its single atomic JSON Patch
tests the captured UID, the fresh resourceVersion, exact container/Service-port
identity, and every owned injected field before restoring all owned fields.
Unrelated metadata or spec edits are preserved: the runner adopts their fresh
resourceVersion as the compare-and-swap guard and touches only owned fields.
It refuses replacement UID, identity drift, or any third-party change to an
owned field. Baseline and post-injection generations are audited so unrelated
spec drift is visible without using a stale generation or resourceVersion as a
restore guard.

A manual restore cancels the timer only after a fresh read confirms the exact
baseline, including whether each field was originally absent. The watchdog
does not cancel itself; it exits successfully after confirming restoration.

## Approved interface after GO

Choose a unique lowercase run ID. `prepare` may use the reviewed source path;
all later actions must use the frozen path printed by `prepare`:

```sh
sudo python3 deploy/incident-drills.py prepare \
  --runid <unique-run-id> --drill <approved-drill>

sudo /usr/bin/python3 \
  /var/lib/ts-capstone-incident-drills/<unique-run-id>/runner.py \
  start --runid <unique-run-id>

sudo /usr/bin/python3 \
  /var/lib/ts-capstone-incident-drills/<unique-run-id>/runner.py \
  status --runid <unique-run-id>

sudo /usr/bin/python3 \
  /var/lib/ts-capstone-incident-drills/<unique-run-id>/runner.py \
  restore --runid <unique-run-id>
```

`watchdog` is an internal systemd entry point. Operators must not invoke it.
There is no `--namespace`, arbitrary manifest, generic patch, duration override,
or filesystem-path option.

## Operator sequence after GO

1. Verify the reviewed file hash, root shell, cluster context, approved change
   window, named incident commander, and an observer with a second session.
2. Run the workload-health and observability preflight defined by the drill
   orchestrator. Do not prepare or start if any gate is unhealthy.
3. Run `prepare`, inspect its JSON output, then use only the printed frozen
   runner path.
4. Run `start`. Confirm the JSON says `injected` and records the watchdog unit.
   If it reports `mutation_unknown`, do not retry `start`; inspect `status` and
   allow the watchdog or run manual `restore`.
5. Observe only until the listed hard limit. Never start a second run while a
   run is prepared, armed, injected, unknown, or unrecovered.
6. Restore early when the objective is met. Keep the session open until restore
   reports `restored` or `already_restored`, then verify workload health.
7. Preserve the root-only `audit.jsonl`, timer status, workload evidence, and
   pre/post generations. Do not remove the run directory during the review.

If restore refuses identity or owned-field drift, do not hand-edit state and do
not force a patch. Keep the watchdog retrying, page the incident commander, and
have an approver reconcile the live resource. If unrelated fields changed, the
normal guarded restore is safe and preserves them.

## Completed historical-record archival

After independent operational review, a terminal restored run may be archived,
not removed, from the active base. Never archive an active or unknown run, edit
frozen state, or force cleanup. Verify frozen status `restored`, live owned
fields at baseline, both timer and service `not-found/inactive/dead`, empty job
state, a real root-owned `0700` source on the same filesystem, and an absent
destination. Rename the entire unchanged directory to
`/var/lib/ts-capstone-incident-drills-archive/<run-id>`, then record matching
before/after file hashes, modes, and owners in a separate location receipt.
Preserve evidence always. This exception applies only after terminal proof and
review; it does not weaken restore guards. The Catalogue
[postmortem](../postmortem.md#catalogue-crash-loop-attempts) records the
`12:36Z` archive proof.

## Offline validation

Tests are mock-only and must be run on the designated EC2 workstation under the
project's normal Python; they never contact k3s:

```sh
python3 deploy/test-incident-drills.py
```

Passing tests are necessary but not a GO. Record the tested source SHA-256 and
obtain a fresh security review before any installation or drill.

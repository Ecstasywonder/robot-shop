# Catalogue crash-loop safety attempts

**Classification:** recovered, passing student-led controlled simulation with
two earlier aborted safety attempts. It is not an instructor-led drill.

## Record

- Run ID: `run20261028-catalogue-crashloop-01`
- Date: `2026-10-28`
- Injection time: not recorded here; do not infer it.
- Initial result: injection occurred, but post-confirmation reported
  `mutation_unknown`.
- Observation: only the baseline was saved. No observer observation loop began,
  so this record does not claim an alert outcome, continuous old-Pod uptime, or
  a 15-minute healthy-observation window.

## Safety outcome and reconciliation

The regular frozen restore correctly refused to overwrite a field it identified
as third-party owned. The mismatch was representational: Kubernetes omitted an
explicit `initialDelaySeconds: 0` from the actual readiness probe, while every
other captured probe value, the command, snapshot, and workload UID matched.
The tool had expected the explicit zero.

At `2026-10-28T12:06:34.921820Z`, the operator manually reconciled the
Deployment with one atomic JSON Patch. The patch tested the captured UID, fresh
resource version, container name, actual command, and actual probe, then
removed only the command and readiness probe that had originally been absent.
It did not edit frozen state, force a change, or alter unrelated fields. The
root-owned `manual-reconciliation.json` is retained with the archived live
operator run directory.

The frozen restore then returned `already_restored`. At `12:08:36Z`, the old
`catalogue-54bb598557-49lf9` Pod was Ready `1/1` with zero restarts, and zero
drill units were loaded.

## Subsequent attempts and current state

This safety abort exposed an equivalence error in the runner's probe comparison:
the Kubernetes API may omit a zero-valued `initialDelaySeconds`. The expected
probe representation, regression coverage, and Kubernetes server-side dry-run
were validated and independently reviewed for GO on 28 October.

`run20261028-catalogue-crashloop-02` stopped before mutation because the strict
state validator could not parse the old terminal run's explicit
`initialDelaySeconds: 0`. No run directory or rollback timer was created; only
an observer baseline exists. The terminal directory for run 01 was then
archived outside the active registry without editing frozen state: at
`2026-10-28T12:36:00.108680Z`, root verified restored status, absent live
Catalogue command/probe, inactive/not-found units, empty job state, root-owned
`0700` same-filesystem source, and an absent destination. The whole unchanged
directory was renamed to
`/var/lib/ts-capstone-incident-drills-archive/run20261028-catalogue-crashloop-01`;
before/after file hashes, modes, and owners matched in a receipt outside the
active base. Canonical evidence is archived at
`docs/evidence/drills/run20261028-catalogue-crashloop-01/`, including baseline,
samples, audit, state, manual reconciliation, and location receipt.

`run20261028-catalogue-crashloop-03` passed a fresh baseline of 10 healthy
inactive rules and 27 Ready workloads at `12:36:40Z`; injection occurred at
`12:36:42Z` with a 240-second independent guard and a 1,500-second observer at
30-second intervals. `CrashLooping` was pending at `12:37:16Z`, reset at
`12:37:49Z`, was pending again at `12:38:22Z`, and fired at `12:40:01Z`.
The independent watchdog attempted restore at `12:40:42Z` and recorded restored
state at `12:40:43Z`; the alert cleared at `12:41:07Z`.

The first post-clear Slack-success rate-window increase was
`1.1111111111111112` with failure increase `0` at `12:41:07Z`. It is neither
an integer delivery count nor evidence of human acknowledgement, and is not
claimed to have occurred while the alert was firing.

## Run 03 recovery closure

The observer recorded one baseline and 39 samples (40 JSONL lines). Its final
sample at `12:57:37Z` was 16 minutes 54 seconds after restored state and 16
minutes 30 seconds after alert clearance. Every sample recorded `critical=[]`.
The final sample had no Prometheus or Alertmanager alerts; web, payment, and
Cart RED error rates were zero; no Catalogue error series existed; Catalogue
request rate was positive at `0.4148/s`; payment 2xx rate was `0.1037/s`; and
32 spans were present. These are bounded observations, not proof that the Pod
was uninterrupted between checks.

At `12:58:06Z`, a fresh check found all 27 workloads Ready with zero restarts,
state `Restored`, and the original Catalogue Pod UID Ready. The observer stopped
under controlled closure before its natural `13:01Z` deadline; source baseline
records were valid. Run 03 is a recovered, passing student-led simulation.
Its [canonical archive](../evidence/drills/20261028-catalogue-crashloop-03/)
contains the baseline, samples, audit, and restored-state record.

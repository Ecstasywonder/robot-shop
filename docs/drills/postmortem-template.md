# Student-led simulation postmortem template

Use one completed copy for each controlled simulation. This template records a
student-led simulation, not an instructor-led incident drill. Do not present a
simulation as instructor-led or as accepted by TS Academy unless the Academy
confirms that decision.

## Record

- Simulation ID and name:
- Classification: student-led controlled simulation
- UTC start, injection, recovery, and end times:
- Operator and reviewer:
- Runner and observer SHA-256 values:
- Scope and declared hard rollback limit:
- Baseline evidence reference:

## Customer and service impact

- Customer-path symptom and observed duration:
- Affected workload, Service, and telemetry component:
- Explicitly unaffected workloads and persistent resources:
- Whether payment outcome was ambiguous:

## Timeline

| UTC time | Observation or action | Evidence reference | Result |
| --- | --- | --- | --- |
| | | | |

## Evidence and alerting

- Exact injected field and pre-injection value:
- Workload state: Pod UIDs, readiness, restart counts, events, and node conditions:
- Gateway RED request, error, and latency evidence:
- Alert lifecycle: pending, firing, resolved, and Slack notification outcome:
- Logs and tracing evidence, including known telemetry gaps:
- Recovery evidence, including the final customer-path response:
- At least 15 minutes of post-recovery health evidence:

Payment item counters may corroborate post-gateway accounting activity. They do
not alone prove a completed purchase; use bounded gateway HTTP 2xx and HTTP 200
customer-path evidence for that claim.

## Analysis

- Trigger and immediate cause:
- Causal chain from injected condition to observed symptom:
- Why rollback/recovery interrupted the chain:
- Competing explanations considered and evidence for or against each:
- Confidence, uncertainty, and observability limitations:

## Follow-up actions

| Action | Purpose | Owner | Due date | Status |
| --- | --- | --- | --- | --- |
| | | | | |

## Closure

- Guard/watchdog state after recovery:
- Final resource configuration compared with baseline:
- Evidence location and immutable references:
- Reviewer conclusion:
- Instructor/Academy acceptance status: pending unless separately confirmed.

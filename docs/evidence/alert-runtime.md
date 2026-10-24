# Alert and Runbook Runtime Evidence

Date: 24 October 2026 (Africa/Lagos).

## Loaded Rules and Receiver

Two release-labelled PrometheusRule resources provide nine Robot Shop alerts:
Cart gateway availability degradation, absent Cart traffic, absent Fluent Bit
RED endpoint, other monitored gateway errors, unexpected web traffic idleness,
OOM/restart correlation, crash loops, unavailable Deployments, and unavailable
Redis StatefulSet replicas. Prometheus loaded all nine with `health=ok`, no
evaluation errors, and `state=inactive` at the final check.

Metrics Helm revision 4 changed only the Slack receiver's text. It includes
the alert name, service, severity, and fixed published runbook URL:

https://github.com/Ecstasywonder/robot-shop/blob/master/docs/runbook.md

The webhook remains in the existing mounted Secret through `api_url_file`.
Its value was not printed or committed. Global routing, inhibition, grouping,
and the existing persistent volumes were preserved.

## Delivery Test and Human Confirmation

An explicitly labelled `CapstoneSlackDeliveryTest` used the existing
`CONNECTIVITY TEST (not an incident)` title. No application fault or real
payment was introduced.

The first informational test and the early warning-test observation produced
no notification attempt. An inhibition cause was not established from the
global suppression counter alone. The warning test was active, selected
`slack-tscapstone`, and had empty inhibition, mute, and silence lists.

The warning test beginning at `2026-10-24T14:47:05Z` retained the same labels
and fingerprint while its expiry was extended once to eight minutes from the
refresh. This allowed observation across the existing five-minute group
interval; no production timer or inhibition rule was weakened. The Slack
notification counter advanced from 2 to 3 with zero failures.

The user then explicitly confirmed that the new message appeared in
Breatha.org's `#tscapstone` and that its GitHub runbook link opened.

At the independent final check around `2026-10-24T19:47Z`, the delivery test
was no longer active. Slack notifications totalled 4, with every reported
failure-reason counter at zero. The additional notification is consistent
with resolution; a separate human acknowledgement of the resolved message
was not requested or claimed.

## Final Health and Boundaries

The final read-only check found 13 Robot Shop, five voting, eight observability,
and one Fluent Bit workload Ready, all with zero restarts. This proves loaded
rules and successful Slack/link delivery under the observed conditions, not
24-hour SLO compliance or coverage of every possible failure.

This connectivity test and the separate synthetic error-log check are not
the required instructor-led incident drill. Its fault, mitigation, alert
evidence, root-cause analysis, and blameless postmortem remain pending.

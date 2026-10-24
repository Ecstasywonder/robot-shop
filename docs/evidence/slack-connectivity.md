# Slack receiver connectivity evidence

## Scope

This is a receiver connectivity test, not an instructor incident, outage, or
Prometheus alert demonstration. The destination is Breatha.org `#tscapstone`.
The incoming-webhook URL was never read, printed, committed, or supplied to
Helm.

## Configuration and health

- `2026-10-22T15:35:11Z`: metadata-only verification found the existing
  `observability/slack-webhook` Secret. Its data was not read or changed.
- `2026-10-23T06:24:25Z`: `kube-prometheus-stack` Helm revision 3 completed
  using official chart `92.7.0` and the full reviewed values file.
- Helm lint, rendering, server-side dry run, and `amtool check-config` of the
  rendered configuration passed before upgrade.
- The Alertmanager custom resource was Available; its pod was `2/2` Ready with
  zero restarts after upgrade. Monitoring PVC identities were unchanged.
- The receiver reads `api_url_file` from the mounted Secret. The Robot Shop
  child route matches `capstone=robot-shop`, groups by `namespace` and
  `alertname`, and has `continue: false`. Watchdog and the null receiver remain
  present.

## Controlled test

One alert only was submitted to Alertmanager's private `127.0.0.1` port-forward
API. It used `alertname=CapstoneSlackDeliveryTest`,
`capstone=robot-shop`, `namespace=robot-shop`,
`service=slack-connectivity-test`, and `severity=test`; it expired three
minutes after submission. Its title is explicitly rendered as `CONNECTIVITY
TEST (not an incident)`.

At `2026-10-23T06:27:05Z`, aggregate Alertmanager metrics showed Slack
notification total `1`, Slack delivery failures `0`, and configuration reload
success `1`. This proves firing delivery. The resolved-notification observation
was pending at this capture because the alert had not completed its expiry and
group-interval window. No second test was submitted.

The user also confirmed that the explicitly titled `CONNECTIVITY TEST (not an
incident)` message was visible in `#tscapstone`. This is channel-side
confirmation of the same single firing notification, not a second delivery.

All temporary Alertmanager port-forwards were removed after collection; the
final process check reported `0` remaining.

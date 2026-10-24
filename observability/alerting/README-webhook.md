# Private Slack webhook entry

Target: Breatha.org workspace, `#tscapstone`. On 22 October the user completed
secure entry. A metadata-only cluster check confirmed the independently managed
`observability/slack-webhook` Secret, created at `2026-10-22T15:35:11Z`.
Alertmanager routing and delivery verification are separate steps. The chat
connector does not supply an Alertmanager credential. The URL must never be
sent through chat or committed.

Run `configure-slack-webhook.sh` with Bash in an interactive SSH terminal on
the K3s node. It validates the host and URL format, disables shell tracing,
prompts without echo, and submits a mode-0600 temporary file directly to the
Kubernetes API. The temporary file is removed on normal exit or interruption.
The URL is never an external process argument or exported environment variable.
Do not prefix the command with the URL or paste it into shell commands.

The resulting Secret is `observability/slack-webhook`, key `url`. Server-side
apply avoids a last-applied annotation containing a second copy. A cluster
administrator can still read Kubernetes Secrets; base64 is not encryption, and
this process does not claim an independently encrypted secret backend.

The Alertmanager receiver is active as of `2026-10-23T06:24:25Z` (Helm release
revision 3). It mounts the Secret as a file at
`/etc/alertmanager/secrets/slack-webhook/url`; the URL is not Helm input. The
route is limited to alerts labelled `capstone=robot-shop`, grouped by namespace
and alert name, and does not continue into any later route. Watchdog remains
discarded. A one-time, self-expiring receiver connectivity test was accepted by
Alertmanager and its firing notification was delivered with no Slack delivery
failures. This demonstrates the receiver path, not an instructor incident or a
Prometheus alert drill. The user confirmed that the labelled test message was
visible in `#tscapstone`.

The resolved-notification observation and the capstone SLO/runbook drill remain
separate follow-up evidence. Keep the webhook URL out of chat, commits, Helm
values, rendered manifests, and command arguments.

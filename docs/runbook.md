# Robot Shop Incident Response Runbook

Use this runbook for the four monitored customer paths (`web`, `catalogue`,
`cart`, and `payment`), the supporting Kubernetes workloads, and failures in
the monitoring pipeline. It covers `CartGatewayAvailabilityDegraded`,
`CartGatewayTrafficAbsent`, `FluentBitRedMetricsUnavailable`,
`RobotShopGateway5xxRateHigh`, `RobotShopGatewayTrafficIdle`,
`RobotShopContainerOOMKilled`, `RobotShopContainerCrashLooping`, and
`RobotShopDeploymentUnavailable`, and `RobotShopRedisStatefulSetUnavailable`.
These alerts link to this exact file in the
personal fork. The monitoring coverage and known blind spots are recorded in
[`monitoring-coverage.md`](monitoring-coverage.md).

This runbook prepares for the instructor-created incident. It does not claim
that the instructor drill has happened. Any self-created test must be labelled
**simulation**, kept separate from drill evidence, and stopped before it risks
customer data or persistent state.

## 1. Stabilize and Preserve Evidence

1. Record the alert name, UTC start time, affected service, dashboard window,
   and the first customer-visible symptom. Do not paste credentials, request
   URIs or request lines, headers, bodies, payment data, webhook URLs, or
   personal data into Slack or tickets.
2. Decide whether this is customer impact, telemetry loss, or both. Missing
   traffic, logs, or traces means **unknown**, never healthy.
3. Capture the current Pod identities, restart counts, workload revisions,
   events, node conditions, and Helm history before changing anything.
4. Reduce non-essential load if it is contributing to impact. Change only the
   affected workload and only after evidence supports the change.
5. Assign a timekeeper. Record every command that changes state, who ran it,
   the reason, and its result.

Run these read-only checks on the K3s EC2 node:

```bash
date -u
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl -n robot-shop get deployments,statefulsets,pods -o wide
sudo k3s kubectl -n robot-shop get pods \
  -o custom-columns='NAME:.metadata.name,UID:.metadata.uid,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,REASON:.status.containerStatuses[*].lastState.terminated.reason'
sudo k3s kubectl -n robot-shop get events --sort-by=.lastTimestamp
sudo k3s kubectl -n robot-shop get services,endpointslices
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml /usr/local/bin/helm history robot-shop -n robot-shop
```

For the affected Pod, retain bounded current and previous logs and its full
status. Replace placeholders only after identifying the exact Pod and
container; do not collect secrets or dump every cluster log.

```bash
sudo k3s kubectl -n robot-shop describe pod <pod>
sudo k3s kubectl -n robot-shop logs <pod> -c <container> --since=15m --tail=200 --timestamps
sudo k3s kubectl -n robot-shop logs <pod> -c <container> --previous --tail=200 --timestamps
```

## 2. Triage Matrix

| Observed symptom | Confirm or refute with | Plausible mechanisms | Scoped mitigation |
| --- | --- | --- | --- |
| `web` errors, latency, or unexpectedly idle traffic | RED dashboard by service; web access logs; load Pod state; backend endpoint readiness | Web rollout/configuration, stopped or stuck load, downstream failure, DNS or network policy, saturation | Restore the declared steady load only after the gateway is safe to receive it. If timing and evidence identify a bad release, roll back only the Robot Shop release to a known-good revision. |
| `catalogue` errors or latency | Catalogue gateway RED signal; catalogue Pod current/previous logs; MongoDB Pod; Service `port`/`targetPort`; Ready EndpointSlices; and the declared container listener | Catalogue process failure, MongoDB unavailable, bad rollout, Service-to-listener port mismatch, connectivity failure | Restore the authoritative Helm configuration or a known-good catalogue revision with the smallest scoped change. Preserve the MongoDB PVC; never delete data to recover the API. |
| `cart` 5xx, absent traffic, or latency | Cart RED signal and SLO alert; cart/web Pod state; Redis Pod, Service, and endpoints | Cart scaled to zero, bad cart/web rollout, Redis unavailable, connectivity failure, capacity constraint | For a confirmed accidental scale-down, restore the reviewed one-replica desired state. Otherwise roll back only a proven bad revision or reduce load. |
| `payment` errors or latency | Payment gateway RED signal; payment/web logs; payment endpoints; one trace when tracing is healthy | Payment process failure, dependency timeout, bad rollout, tracing/instrumentation failure, network policy | Stop repeated payment attempts if outcome is ambiguous. Restore only a known-good payment revision after preserving evidence; do not manufacture a successful payment. |
| One Pod is `CrashLoopBackOff` or repeatedly restarts | `describe pod`, events, current/previous logs, last termination reason, rollout revision, and whether an older replica remains Ready | Application crash, missing configuration, probe failure, OOM, bad image; an old Ready Pod can mask a looping replacement | Pause further rollout. Roll back a correlated bad revision; do not globally restart all workloads. |
| Pod shows `OOMKilled` / exit 137 | Last termination reason, container limit, restart delta, node `MemoryPressure`, other Pod evictions | Container exceeded its own cgroup memory limit; less commonly node-wide pressure/eviction | First distinguish container-limit OOM from node pressure. Remove/reduce the triggering load or correct the bounded code/configuration. Do not blindly raise limits, add nodes, or enable autoscaling. |
| Deployment is unavailable after a release | Deployment conditions, ReplicaSets, events, image digest, readiness/liveness failures, Helm history | Bad image/config, failed probe, unschedulable Pod, missing dependency | Stop the rollout and select a verified known-good Helm revision. Do not guess the revision or roll back unrelated services. |
| Redis StatefulSet has unavailable replicas | Redis Pod, StatefulSet/PVC status, endpoints, events, and the cart error window | Redis process failure, PVC/mount failure, readiness failure, connection or network policy problem | Preserve Redis state. Recover only the verified Redis workload or a correlated known-good release; do not delete the PVC or reseed data during triage. |
| Redis, MongoDB, MySQL, or RabbitMQ errors | Application error timestamps correlated with dependency Pod readiness, endpoints, events, and bounded logs | Dependency restart, PVC/mount failure, connection refusal/timeout, DNS/network policy | Preserve PVCs and queue/database state. Recover the failed dependency from its declared workload; do not delete/reseed storage or purge queues during triage. |
| Service name fails or requests time out | Service selector, Service `port`/`targetPort`, Ready EndpointSlices, actual container listener, CoreDNS health, namespace NetworkPolicies, application connection errors | Empty/mismatched endpoints, wrong Service-to-listener port, DNS failure, blocked ingress/egress | Correct only the proven selector/port/policy defect through reviewed source. Do not delete Pods/PVCs, disable all NetworkPolicies, or open public/Internet access. |
| PVC pending, mount error, or node disk warning | PVC/PV status, events, local-path provisioner health, node conditions, scoped filesystem usage | Provisioning/mount failure, local disk pressure, exhausted retained data | Stop write amplification where safe and preserve data. Do not delete/resize a PVC or clean node storage without explicit review and a recoverable plan. |
| The single K3s node is NotReady or the API is unstable | Node conditions/events, K3s service state, and authorized read-only EC2 instance/system status checks | K3s failure, host resource pressure/reboot, EC2 reachability, storage, or network fault | Stop application rollouts and escalate as a platform incident. Do not terminate/rebuild the instance or detach storage during triage. |
| RED data, logs, or traces disappear while requests may continue | Collector/target health, Prometheus target, Fluent Bit/Loki, Collector/Jaeger readiness, recent config change | Telemetry workload failure, scrape/label mismatch, backpressure, NetworkPolicy, storage issue | Treat SLO state as unknown. Restore the affected telemetry component from reviewed configuration; do not call the application healthy from absent signals. |
| Alert appears in Prometheus but not Slack | Alertmanager alert/notification status, capstone label, route, receiver health | Missing `capstone="robot-shop"`, route mismatch, receiver/config failure | Preserve the private webhook Secret. Correct labels/routing through source; never print or inline the webhook URL. |

The four gateway RED signals observe requests seen by the `web` access log;
they do not prove that every internal hop or datastore is healthy. Correlate a
gateway symptom with workload state and dependency evidence before naming a
root cause.

## 3. Key Diagnostic Branches

### Container OOM or node pressure

A last state of `OOMKilled` with exit code 137 and a container memory limit is
evidence of a container OOM, but confirm node state too. Node `MemoryPressure`,
eviction events, and failures across unrelated Pods support node-wide pressure.
The sum of declared limits being greater than node capacity is an overcommit
risk; it does not by itself prove why one container was killed. The node
exporter is disabled, so this stack does not provide host memory or filesystem
time series. Use Kubernetes status/events and direct, read-only node checks.

```bash
sudo k3s kubectl describe node ts-academy-k3s
sudo k3s kubectl -n robot-shop get pod <pod> -o yaml
sudo k3s kubectl -n robot-shop top pod <pod> --containers
```

The `top` command is supplementary and may be unavailable or may miss a short
peak. For a surviving container on cgroup v2, inspect its current cgroup only
when the path and Pod identity have been verified; preserve `memory.events`
and `memory.peak` rather than changing cgroup files.

### Service discovery or network policy

First verify that the Service selector produces Ready EndpointSlices, then
compare the Service `port` and `targetPort`, endpoint port, and the actual
container listener. Ready Pods and non-empty EndpointSlices do not prove that
the selected target port accepts traffic. Check CoreDNS and the relevant
policies next. If an existing application image already contains a DNS/client
tool, a bounded read-only probe is acceptable; do not install tools inside a
running container during the incident. Restore the authoritative Helm
configuration with the smallest scoped change; do not compensate by deleting
Pods or changing NetworkPolicies blindly.

```bash
sudo k3s kubectl -n robot-shop describe service <service>
sudo k3s kubectl -n robot-shop get endpointslices \
  -l kubernetes.io/service-name=<service> -o wide
sudo k3s kubectl -n robot-shop get networkpolicies -o yaml
sudo k3s kubectl -n kube-system get deployment,pods -l k8s-app=kube-dns
```

### Persistent dependency or node disk

Do not equate a Ready datastore Pod with data integrity. Correlate mount and
I/O events with the application error window, check that claims remain Bound,
and preserve claim/PV identities.

```bash
sudo k3s kubectl -n robot-shop get pvc -o wide
sudo k3s kubectl get pv
sudo k3s kubectl -n robot-shop get events --field-selector type=Warning --sort-by=.lastTimestamp
df -h /var/lib/rancher/k3s/storage
```

Escalate before any action that can discard or rewrite database, queue, or PVC
state. Recovery may require an instructor-approved restore procedure rather
than an improvised restart.

### Telemetry blindness

`CartGatewayTrafficAbsent` or `FluentBitRedMetricsUnavailable` means the Cart
SLO is unknown. Check each layer in order: source log, Fluent Bit, RED metrics
target, Prometheus, Grafana/Alertmanager, then Loki. For tracing, check payment
instrumentation, Collector receipt/export, and Jaeger storage/query.
`PaymentTraceCollectorUnavailable` means the known single Collector has fewer
than one available replica; it is tracing blindness, not proof of payment
failure or of a final payment 2xx. If its kube-state-metrics series are absent,
tracing health is unknown and the target/scrape path needs investigation. A
healthy Jaeger UI without a matching span is not proof that export works. After
recovery, use fresh logs and RED data and require a span started after the
Collector recovered; buffered pre-recovery spans do not prove the repaired
pipeline works.

```bash
sudo k3s kubectl -n observability get pods,services
sudo k3s kubectl -n log-collection get daemonsets,pods,services
sudo k3s kubectl -n observability get prometheusrules,servicemonitors
sudo k3s kubectl -n observability get events --sort-by=.lastTimestamp
sudo k3s kubectl -n log-collection get events --sort-by=.lastTimestamp
```

The RED metric uses application `service="cart"` and scrape
`namespace="log-collection"`; the Fluent Bit target uses
`service="fluent-bit"`. Confirm live labels and targets before enabling or
changing alerts. Never substitute an absent error counter for zero errors
unless a valid request series exists.

## 4. Conditioned Mitigations

For a confirmed accidental Cart scale-down, first confirm the reviewed Helm
values still require one replica and no upgrade is active. Restore the declared
state, rather than adding capacity to mask another failure:

```bash
sudo k3s kubectl -n robot-shop scale deployment/cart --replicas=1
sudo k3s kubectl -n robot-shop rollout status deployment/cart --timeout=120s
```

For a bad release, use Helm history and evidence to select a known-good
revision. Record the current and target revisions before rollback. A rollback
is not appropriate when the same external dependency, node, PVC, or network
fault will remain after it.

Never use these as generic mitigations:

- deleting a namespace, PVC, PV, database contents, or queue contents;
- restarting every deployment or the K3s node;
- disabling NetworkPolicies or opening public/Internet access;
- increasing all resource limits, adding EC2 instances, autoscaling, or adding
  a load balancer without a demonstrated capacity mechanism;
- modifying or exposing Slack, Grafana, or application credentials.

Stop and escalate immediately for suspected data corruption, ambiguous payment
outcomes, credential exposure, control-plane failure, a NotReady single node,
or any mitigation requiring destructive persistent-state changes. Also
escalate if customer impact continues for 10 minutes without a supported
mitigation, or if a change makes another service unhealthy.

## 5. Recovery Criteria

Pod readiness alone is insufficient. Declare recovery only when all applicable
checks pass for a recorded observation window:

- the affected workload has its declared replicas Ready, with stable Pod UIDs
  and no new restarts or OOM events;
- a real customer-path request succeeds; for the purchase path, use bounded
  gateway payment 2xx evidence and a bounded HTTP 200 path without
  duplicate/ambiguous payment behavior. Payment counters only corroborate
  post-gateway accounting activity and do not prove completion;
- request rate resumes, the affected service 5xx ratio falls, and latency
  returns near its pre-incident baseline;
- fresh post-recovery logs are searchable by bounded `service` and `level`
  labels, and fresh RED data shows the affected path recovering;
- telemetry targets are healthy and the alert resolves because the signal
  recovered, not because traffic or collection disappeared;
- when tracing is in scope, a payment request started after Collector recovery
  produces a complete trace in Jaeger; and
- unrelated Robot Shop, voting, and observability workloads remain healthy.

Continue observing after apparent recovery long enough to cover the original
failure interval or at least 15 minutes for a short drill. Do not close an
incident while the SLO is unknown.

## 6. Root Cause and Drill Record

Keep facts and explanations separate:

1. **Observed evidence:** exact timestamps, customer symptoms, relevant metric
   values, Pod UID/restarts, events, logs, trace ID, revisions, and actions.
2. **Most plausible mechanism:** the causal chain from initiating condition to
   customer impact, including why the mitigation interrupted that chain.
3. **Competing explanations:** what else could produce the symptom and the
   evidence that supports or refutes each possibility.
4. **Confidence and uncertainty:** state what was not observable and what
   additional evidence would change the conclusion.
5. **Remediation:** immediate recovery, durable prevention, owner, and due date.
6. **Validation:** successful request/purchase, RED and telemetry recovery,
   restart stability, and a bounded recurrence test.

Build one timestamped causal chain across the recent code/image/configuration
change, gateway signal, application logs, payment trace, Kubernetes event,
network or endpoint state, datastore/queue behavior, and EC2/node condition as
applicable. Check whether retries, timeouts, or concurrent requests amplified
the original fault or created duplicate work. Temporal correlation is a
hypothesis until an observation or controlled validation connects the steps.

Write the postmortem only after the instructor-created incident is complete.
It must be blameless and must not convert a simulation, Slack connectivity
test, prior load-generator OOM investigation, or monitoring preflight into the
required drill. The course supplied no runbook template, so this is an
equivalent authored runbook for the required alert-linked response workflow.

### Verified simulation learnings (not instructor-drill evidence)

- A deployed Nginx 1.20 routing regression showed that an `error_page`
  fallback can lose the original route when the map uses `$uri`. The correction
  maps `$request_uri` with `^/+api`: Nginx can normalize routing while the raw
  request target retains repeated leading slashes, as happens when a Locust
  host ends with `/` and its request begins with `/`. This is a configuration
  lesson, not an instruction to log request targets. The deployed correction
  was verified from source `14547...` at Helm revision 7, where the live Cart
  alert passed; it does not certify 24-hour Cart SLO compliance.
- The completed catalogue crash-loop simulation is recorded in
  [`drills/catalogue-crashloop.md`](drills/catalogue-crashloop.md): an older
  Pod stayed Ready while its bad replacement looped, the alert fired, and the
  rollback was evidenced. The drill tool's initial-delay omission was not an
  application failure. Other planned simulations need their own execution
  evidence before any outcome is claimed.

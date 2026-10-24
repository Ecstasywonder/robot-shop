# Logging NetworkPolicy Check

`check-network.py` is an operator-only, temporary-pod probe for the logging
NetworkPolicy. It is not an application manifest and must be run only from the
managed cluster operator host with root access to `k3s kubectl`; it never copies
kubeconfigs, service-account tokens, SSH keys, or credentials into the pod.

The probe starts with a positive control: it creates a separate, short-lived
pod in `robot-shop` using the already cached, digest-pinned Python payment
image. The pod has only the unique
`capstone.tsacademy/flow=network-positive-control` label, deliberately outside
every Robot Shop workload selector and the logging-flow selector. It has no
service-account token, no host paths, a read-only root filesystem,
RuntimeDefault seccomp, no capabilities or privilege escalation, and bounded
resources. It must connect to `example.org:443` within three seconds, then is
deleted only after its UID is re-checked. If that independent control fails,
the script returns an inconclusive failure and never creates the logging test
pod; an external deny would otherwise not prove NetworkPolicy enforcement.

This avoids using the live `payment` workload as the control. The reviewed
tracing policy will intentionally restrict payment egress, so application-pod
reachability would no longer establish whether logging-policy egress denial is
working.

When the control succeeds, the script creates one uniquely named,
non-privileged pod in `log-collection` using the already cached, digest-pinned
payment image. It has the dedicated logging-flow label used by the policy, but
not the Fluent Bit DaemonSet selector labels; no service-account token, no host
paths, no Secret access, a read-only root filesystem,
RuntimeDefault seccomp, no capabilities, no privilege escalation, and bounded
resources. Its standard-library-only Python probe requires DNS for Loki and
the Kubernetes API, permits TCP to the API on 443 and Loki on 3100, and denies
Prometheus on 9090 and `example.org` on 443. Pod output is one JSON object with
fixed boolean field names only.

The operator process reads Kubernetes objects as JSON, waits no longer than 90
seconds for the probe pod, captures at most 4 KiB of output, and exits zero
only when every expectation passes. Cleanup runs on success and failure, but
first reads the object metadata and deletes only when the current UID exactly
matches the UID returned at creation. A failed create never deletes anything.

Run it only after the `log-collection` NetworkPolicy and Loki service have
been deployed and reviewed:

```bash
sudo python3 'Capstone 2/observability/logging/check-network.py'
```

This tests the intended logging-flow policy and selected flows, not full compromise
resistance. A namespace administrator can label a workload as Fluent Bit;
node/host exceptions and broader control-plane behavior remain out of scope.
Kubernetes NetworkPolicy enforcement can evaluate service traffic after DNAT,
so verify the actual API destination IPs and the source policy after a
Terraform/network rebuild. Treat a pass as one bounded evidence point, not as
a substitute for reviewing the rendered policy and cluster isolation model.

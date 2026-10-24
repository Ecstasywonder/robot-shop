# Payment tracing

This source prepares the course's required trace for one service only:
`payment`. It is deliberately manual instrumentation, not Flask or Requests
auto-instrumentation. The sole span name is `payment.pay`; it has no request,
customer, URL, header, body, cart, identifier, exception, or status-description
attributes. Tracing is disabled unless `OTEL_TRACING_ENABLED=true`.

The canonical implementation is in `payment/payment.py` and
`payment/requirements.txt`, with opt-in environment and image wiring in the
existing Helm chart. The custom payment image must be
built and loaded or published as an immutable amd64 digest before updating the
chart's payment image. Do not point a running Deployment at an untested tag.
The current Dockerfile still uses a mutable `python:3.9` base tag and the
Python dependency file is not hash-locked; that pre-existing build
reproducibility/supply-chain gap remains a documented follow-up, not a claim
that the tracing patch solves it. The existing payment application logs its
route user ID and cart body; the new span does not add those fields, and log
sanitization is deliberately outside this narrowly scoped tracing change.

The Collector accepts OTLP/HTTP only at the private service
`otel-collector.observability.svc.cluster.local:4318`, forwards only to Jaeger
OTLP/gRPC, and has bounded processor memory and batches. Jaeger uses its
ephemeral in-memory store with at most 1,000 traces. Its UI is also `ClusterIP`;
use a temporary authenticated operator port-forward for a demo. Trace data is
not durable and is not a production audit record.

The manifests use verified Linux/amd64 digests:

- Collector `otel/opentelemetry-collector@sha256:90692de6afc493cddc6c23bf3dd7ed3772905e448fcf0887ec8876b4d33ff34d`
- Jaeger `cr.jaegertracing.io/jaegertracing/jaeger@sha256:4d9387a02389204ef9a256cf291a36cfbae91983010e403b4d300202d07eff2a`
- Payment `ts-academy/rs-payment-otel@sha256:423ae2c970248b2a4b6be50ba0992bbe434d57b2abb7b7f8bcaa5b4e8ad3f39a`

The payment image is a cluster-local immutable image assembled and tested on
the EC2 workstation. Its `/app/payment.py`, `/app/requirements.txt`, and
`/app/payment.ini` hashes match the canonical source. It must be imported into
each target node's containerd image store before a Helm rollout; there is no
remote registry fallback for this course-only image.

## Rebuild and import the payment image

Run the build and tests on the EC2 workstation, never on the operator laptop.
Use a unique source tag for every build; do not reuse a tag that may already be
cached. The artifact validated for this submission used the tag
`ts-academy/rs-payment-otel:source-edf0e93425a11cb5` and the manifest digest
listed above.

```bash
cd /home/ubuntu/ts-academy-capstone/capstone-2/robot-shop
SOURCE_HASH=$(sha256sum \
  payment/Dockerfile payment/payment.py payment/payment.ini payment/requirements.txt \
  | sha256sum | cut -c1-12)
SOURCE_ID="${SOURCE_HASH}-$(date -u +%Y%m%dT%H%M%SZ)"
IMAGE_TAG="ts-academy/rs-payment-otel:source-${SOURCE_ID}"
docker buildx build \
  --platform linux/amd64 \
  --load \
  --tag "$IMAGE_TAG" \
  payment

docker image inspect "$IMAGE_TAG" \
  --format 'id={{.Id}} os={{.Os}} architecture={{.Architecture}} tags={{json .RepoTags}} digests={{json .RepoDigests}}'
docker run --rm --network none \
  -e PYTHONPATH=/app \
  -v "$PWD/observability/tracing/check-payment-tracing.py:/tmp/check-payment-tracing.py:ro" \
  --entrypoint python \
  "$IMAGE_TAG" \
  /tmp/check-payment-tracing.py /app/payment.py
```

Keep the SSH private key on the operator machine. Configure two strict
host-key-checked SSH aliases there: one for the public EC2 workstation and one
for the private K3s node using the workstation as its jump host. Then stream
the archive directly between the servers; this creates no laptop image file,
copies no key or registry credential to either server, and opens no listener or
security-group port:

```bash
IMAGE_TAG=ts-academy/rs-payment-otel:source-edf0e93425a11cb5
ssh ts-workstation "docker save '$IMAGE_TAG' | gzip -1" \
  | ssh ts-k3s 'gzip -dc | sudo k3s ctr images import -'
```

The foreground SSH processes are the entire relay and close when the pipeline
exits. For this submission the SSH relay was measured but was too slow for the
416,114,784-byte compressed archive. The successful transfer used the included
`serve-image-once.py` helper. Before using that fallback, inspect the existing
EC2 security-group rules read-only; do not add or widen a rule. Binding an EC2
private address does not by itself prevent access through public-IP NAT. Run
the helper only under a short `systemd-run` guard, with the exact cluster
private source address and an unpredictable exact path. It has no directory
listing and handles one request before exiting:

```bash
# EC2 workstation
TRANSFER_DIR=/tmp/ts-payment-image-transfer
WORKSTATION_PRIVATE_IP=172.31.42.166
CLUSTER_PRIVATE_IP=172.31.32.4
TRANSFER_PORT=8000
TRANSFER_NAME="payment-$(openssl rand -hex 16).tar.gz"
install -d -m 0700 "$TRANSFER_DIR"
docker save "$IMAGE_TAG" | gzip -1 > "$TRANSFER_DIR/payment-image.tar.gz"
sha256sum "$TRANSFER_DIR/payment-image.tar.gz"

sudo systemd-run --collect \
  --unit=ts-payment-image-transfer \
  --uid=ubuntu \
  --property=RuntimeMaxSec=900 \
  --property=NoNewPrivileges=yes \
  --property=PrivateDevices=yes \
  /usr/bin/python3 observability/tracing/serve-image-once.py \
  --bind "$WORKSTATION_PRIVATE_IP" \
  --port "$TRANSFER_PORT" \
  --client "$CLUSTER_PRIVATE_IP" \
  --path "/$TRANSFER_NAME" \
  --file "$TRANSFER_DIR/payment-image.tar.gz"
```

Check K3s-node disk headroom first. Download the archive to a mode-0700
temporary directory, then compare its SHA256 with the value obtained from the
workstation over the trusted SSH session. Do not stream an unverified HTTP
response into containerd. Import only after the hashes match:

```bash
# K3s node
TRANSFER_DIR=/tmp/ts-payment-image-transfer
WORKSTATION_PRIVATE_IP=172.31.42.166
TRANSFER_PORT=8000
TRANSFER_NAME="value-delivered-over-trusted-SSH"
install -d -m 0700 "$TRANSFER_DIR"
curl --fail --show-error --location \
  --connect-timeout 5 --max-time 600 \
  --output "$TRANSFER_DIR/payment-image.tar.gz" \
  "http://${WORKSTATION_PRIVATE_IP}:${TRANSFER_PORT}/${TRANSFER_NAME}"
sha256sum "$TRANSFER_DIR/payment-image.tar.gz"
gzip -dc "$TRANSFER_DIR/payment-image.tar.gz" | sudo k3s ctr images import -
```

Verify the transient unit is inactive, its private listener is closed, and the
foreground SSH relay processes are gone. Remove only the owned temporary
archive and helper after the import checks pass.

On the K3s node, identify the imported source tag, inspect its manifest target,
and verify all referenced content is present:

```bash
SOURCE_REF=docker.io/ts-academy/rs-payment-otel:source-edf0e93425a11cb5
sudo k3s ctr images inspect "$SOURCE_REF"
sudo k3s ctr images check --quiet | grep -Fx "$SOURCE_REF"
```

Read `target.digest` from `ctr images inspect`. It is the authoritative OCI
manifest digest after import. Set `images.payment` in `K8s/helm/values.yaml` to
`ts-academy/rs-payment-otel@<target.digest>`. Register that exact digest alias
and prove CRI can resolve it before rendering or upgrading:

```bash
MANIFEST_DIGEST=sha256:423ae2c970248b2a4b6be50ba0992bbe434d57b2abb7b7f8bcaa5b4e8ad3f39a
DIGEST_REF="docker.io/ts-academy/rs-payment-otel@${MANIFEST_DIGEST}"
sudo k3s ctr images tag "$SOURCE_REF" "$DIGEST_REF"
sudo k3s crictl inspecti "$DIGEST_REF"
```

Assert that exact reference in the Helm render before any upgrade. Never
substitute a Docker image ID for the containerd manifest digest, and never
enable tracing until the digest alias resolves through CRI on every target
node.

`networkpolicies.yaml` restricts payment egress to its existing required
dependencies, DNS, and the Collector; the Collector is restricted to DNS and
Jaeger. The existing broad `allow-observability-ingress` policy still permits
same-namespace observability traffic, so these additive policies do not claim
strict Collector/Jaeger isolation. Tighten that existing shared policy through
a separately reviewed observability-wide change before making such a claim.

Before any rollout, validate the rendered chart, both component configs, image
architecture, payment's 100 MiB runtime budget, required dependency egress,
and a synthetic non-customer checkout. The OOM soak is a separate gate.

To catch accidental Kubernetes metadata inside generated ConfigMap data, pipe
the client-normalized Kustomize render through `check-rendered-configs.py`.
The check requires exactly nine resources, verifies both hashed ConfigMap
references, rejects wrapper keys in the mounted bytes, and can extract those
exact bytes for validation with the pinned component images:

```bash
sudo k3s kubectl kustomize observability/tracing > /tmp/tracing-rendered.yaml
sudo k3s kubectl create --dry-run=client \
  -f /tmp/tracing-rendered.yaml -o json \
  | python3 observability/tracing/check-rendered-configs.py
```

After those gates, run from the canonical repository root on the K3s node:

```bash
sudo k3s kubectl apply --dry-run=server -k observability/tracing
sudo k3s kubectl apply -k observability/tracing
sudo k3s kubectl -n observability rollout status deployment/jaeger --timeout=180s
sudo k3s kubectl -n observability rollout status deployment/otel-collector --timeout=180s
```

Kustomize packages the raw component configs and rewrites their content-hashed ConfigMap
references, so a configuration change rolls the consuming Deployment. Each
resource retains its explicit namespace, including the payment policy in
`robot-shop`; do not add a global namespace override. TCP startup/readiness
probes check listeners only, not successful end-to-end trace export. Before
enabling payment tracing, independently verify one synthetic span reaches
Jaeger. Remove obsolete generated ConfigMaps only after checking no live Pod
references them; do not prune unrelated observability resources.

The private OTLP hops use plaintext HTTP and gRPC (`tls.insecure: true`) with
no collector authentication. That is acceptable only for this single-node,
private course demonstration with intentionally data-minimal spans; it is not
a production confidentiality or integrity boundary.

# Initial Robot Shop deployment

This directory holds the namespace policy and a low-rate, intentional baseline load generator for the first Robot Shop rollout. The application chart is patched by `robot-shop-initial.patch` before rendering.

The load generator uses two clients, does not inject payment errors, and runs continuously (`RUN_TIME=0`). It is a functional baseline only; performance testing and observability are configured separately.

The chart routes checkout's payment-gateway check to `http://web:8080/`, an in-cluster HTTP-200 stub. This avoids external PayPal traffic; checkout is deliberately simulated for this course deployment.

The upstream application has demo-oriented database settings and does not define database credentials in its Helm chart. No credentials are generated or committed here. It retains residual demo risks that make it unsuitable for production: MySQL permits an empty root password, RabbitMQ uses `guest`/`guest`, MongoDB has no authentication, and seeded users include plaintext demo passwords. Services remain ClusterIP-only and the namespace NetworkPolicy limits ingress to in-namespace pods, but those controls do not resolve the upstream application credential model.

The chart removes its Instana environment settings. The upstream web image can still contain optional Instana libraries, but without a build-time Instana key the entrypoint removes the active Nginx tracing directives; removal of baked libraries belongs to a later rebuilt-image change.

## EC2 preflight

Run from the reviewed Robot Shop checkout on EC2. Helm and kubectl must already
be available there; these commands do not run on the local laptop.

```bash
helm lint K8s/helm
helm template robot-shop K8s/helm --namespace robot-shop \
  --kube-version 1.36.5 > /tmp/robot-shop-rendered.yaml
bash deploy/test-rendered-validator.sh
kubectl create --dry-run=client --validate=false --namespace robot-shop \
  -f /tmp/robot-shop-rendered.yaml -f deploy/load-generator.yaml -o json \
  | jq -s '[.[] | if type == "array" then .[] elif .kind == "List" then .items[] else . end]' \
  | jq -e -f deploy/validate-rendered.jq
```

The final command must return `true`. Use separate `-f` inputs: concatenating
the load manifest directly onto Helm output without a YAML document separator
can silently replace the final Redis StatefulSet document. kubectl can emit a
JSON stream or a List, so normalize both forms before validating.

## Install order

Apply `deploy/namespace-networkpolicy.yaml` first. Then run server-side dry runs
of both manifest inputs in `robot-shop`. Only after these succeed, install the
application with Helm (`--namespace robot-shop --wait --timeout 12m`). Apply
`deploy/load-generator.yaml` after the application is ready. Keep failed initial
resources available for diagnosis rather than automatically uninstalling them.

Acceptance requires all 13 pods Ready, 12 ClusterIP services, a Bound Redis
claim using `local-path`, and an increasing payment `sold_count` counter under
continuous load. Check that the separate voting namespace remains healthy.

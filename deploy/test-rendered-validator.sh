#!/bin/bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT

jq -n '[range(0; 13) | {
  apiVersion: "apps/v1", kind: "Deployment",
  metadata: {name: ("fixture-" + tostring), namespace: "robot-shop"},
  spec: {replicas: 1, template: {spec: {
    automountServiceAccountToken: false,
    containers: [{name: "fixture", image: ("example/test@sha256:" + ("a" * 64)),
      resources: {requests: {cpu: "50m", memory: "64Mi"},
                  limits: {cpu: "200m", memory: "256Mi"}}}]
  }}}
}] + [{apiVersion: "v1", kind: "Service",
       metadata: {name: "fixture", namespace: "robot-shop"},
       spec: {type: "ClusterIP"}}]' > "$work/valid.json"

jq -e -f "$script_dir/validate-rendered.jq" "$work/valid.json" >/dev/null
jq '. + [{apiVersion:"v1",kind:"ConfigMap",metadata:{name:"web-access-logging",namespace:"robot-shop"},data:{"default.conf.template":"server {}"}}]' "$work/valid.json" > "$work/valid-config.json"
jq -e -f "$script_dir/validate-rendered.jq" "$work/valid-config.json" >/dev/null
jq '. + [{apiVersion:"v1",kind:"ConfigMap",metadata:{name:"robot-shop-load-script",namespace:"robot-shop"},data:{"robot-shop.py":"from locust import HttpUser"}}]' "$work/valid-config.json" > "$work/valid-two-configs.json"
jq -e -f "$script_dir/validate-rendered.jq" "$work/valid-two-configs.json" >/dev/null
cases=0
for mutation in \
  '.[0].kind = "ClusterRole"' \
  '.[0].metadata.namespace = "voting"' \
  '.[0].spec.replicas = 2' \
  '.[0].spec.template.spec.automountServiceAccountToken = true' \
  '.[0].spec.template.spec.hostNetwork = true' \
  '.[0].spec.template.spec.volumes = [{name:"host",hostPath:{path:"/"}}]' \
  '.[0].spec.template.spec.containers[0].image = "example/test:latest"' \
  '.[0].spec.template.spec.containers[0].securityContext.privileged = true' \
  '.[0].spec.template.spec.containers[0].securityContext.capabilities.add = ["NET_ADMIN"]' \
  '.[0].spec.template.spec.containers[0].ports = [{containerPort:8080,hostPort:8080}]' \
  '.[0].spec.template.spec.containers[0].env = [{name:"INSTANA_AGENT_HOST",value:"host"}]' \
  'del(.[0].spec.template.spec.containers[0].resources.limits.memory)' \
  '.[-1].spec.type = "LoadBalancer"' \
  '.[-1].spec.externalIPs = ["192.0.2.1"]' \
  'del(.[0])' \
  '. + [{kind:"ConfigMap",metadata:{name:"unexpected"},data:{"default.conf.template":"server {}"}}]' \
  '. + [{kind:"ConfigMap",metadata:{name:"web-access-logging"},data:{"extra":"server {}"}}]' \
  '. + [{kind:"ConfigMap",metadata:{name:"web-access-logging"},data:{"default.conf.template":""}}]' \
  '. + [range(0;2)|{kind:"ConfigMap",metadata:{name:"web-access-logging"},data:{"default.conf.template":"server {}"}}]' \
  '. + [{kind:"ConfigMap",metadata:{name:"robot-shop-load-script"},data:{"unexpected":"pass"}}]' \
  '. + [{kind:"ConfigMap",metadata:{name:"robot-shop-load-script"},data:{"robot-shop.py":true}}]'; do
  jq "$mutation" "$work/valid.json" > "$work/invalid.json"
  if jq -e -f "$script_dir/validate-rendered.jq" "$work/invalid.json" >/dev/null; then
    printf 'FAIL: accepted invalid fixture: %s\n' "$mutation" >&2
    exit 1
  else
    result=$?
    if [[ $result -ne 1 ]]; then
      printf 'FAIL: validator errored instead of rejecting fixture: %s\n' "$mutation" >&2
      exit "$result"
    fi
  fi
  cases=$((cases + 1))
done
printf 'PASS: baseline and named-ConfigMap fixtures accepted; %s unsafe fixtures rejected\n' "$cases"

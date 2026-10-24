#!/usr/bin/env bash
set +x
set -euo pipefail

if [[ ! -t 0 || ! -t 1 ]]; then
  printf 'Run this script in an interactive SSH terminal on the K3s node.\n' >&2
  exit 1
fi
command -v k3s >/dev/null || {
  printf 'This script must run on the K3s cluster node, not the workstation.\n' >&2
  exit 1
}

if [[ $EUID -eq 0 ]]; then
  kube=(k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml)
else
  kube=(sudo k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml)
fi
"${kube[@]}" get namespace observability >/dev/null

umask 077
secret_file=$(mktemp)
cleanup() {
  unset webhook
  rm -f -- "$secret_file"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

IFS= read -r -s -p 'Incoming Webhook for Breatha.org #tscapstone (hidden): ' webhook
printf '\n' >/dev/tty
if [[ ! $webhook =~ ^https://hooks\.slack\.com/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9_-]+$ ]]; then
  printf 'Expected a Slack Incoming Webhook URL; nothing was stored.\n' >&2
  exit 1
fi
printf '%s' "$webhook" > "$secret_file"
unset webhook

"${kube[@]}" -n observability create secret generic slack-webhook \
  --from-file="url=$secret_file" --dry-run=client -o json \
  | "${kube[@]}" apply --server-side --field-manager=ts-capstone-slack-setup -f -

printf 'Stored observability/slack-webhook. No alert has been sent yet.\n'

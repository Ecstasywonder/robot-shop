#!/usr/bin/env bash
set -euo pipefail

readonly here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly image='prom/prometheus:v3.7.3'
readonly temp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "$temp_dir"
}
trap cleanup EXIT

# Promtool consumes Prometheus rule groups, while the deployable source is a
# PrometheusRule custom resource. The source layout before spec.groups is fixed
# and is converted only inside this disposable test directory.
sed '1,9d; s/^  //' "$here/availability-rules.yaml" > "$temp_dir/rules.yaml"
sed 's/availability-rules.yaml/rules.yaml/' "$here/rule-tests.yaml" > "$temp_dir/tests.yaml"
chmod 755 "$temp_dir"
chmod 644 "$temp_dir/rules.yaml" "$temp_dir/tests.yaml"

docker run --rm --entrypoint /bin/promtool \
  -v "$temp_dir:/rules:ro" "$image" check rules /rules/rules.yaml
docker run --rm --entrypoint /bin/promtool \
  -v "$temp_dir:/rules:ro" "$image" test rules /rules/tests.yaml

#!/usr/bin/env bash
set -euo pipefail

readonly here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly image='prom/prometheus:v3.7.3'
readonly temp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "$temp_dir"
}
trap cleanup EXIT

# Promtool consumes rule groups, while deployable source is a PrometheusRule.
# Convert only in a disposable directory; source files are never modified.
sed '1,9d; s/^  //' "$here/operational-rules.yaml" > "$temp_dir/rules.yaml"
sed 's/operational-rules.yaml/rules.yaml/' "$here/operational-rule-tests.yaml" > "$temp_dir/tests.yaml"
chmod 755 "$temp_dir"
chmod 644 "$temp_dir/rules.yaml" "$temp_dir/tests.yaml"

docker run --rm --entrypoint /bin/promtool \
  -v "$temp_dir:/rules:ro" "$image" check rules /rules/rules.yaml
docker run --rm --entrypoint /bin/promtool \
  -v "$temp_dir:/rules:ro" "$image" test rules /rules/tests.yaml

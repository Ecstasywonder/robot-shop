#!/usr/bin/env bash
set -euo pipefail

# Run on the EC2 workstation only. This is source validation; it never applies a rule.
readonly here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly image='prom/prometheus:v3.7.3'
readonly temp_dir="$(mktemp -d)"
cleanup() { rm -rf "$temp_dir"; }
trap cleanup EXIT

# promtool consumes groups, while the reviewed source is a PrometheusRule CR.
sed '1,9d; s/^  //' "$here/tracing-availability-rules.yaml" > "$temp_dir/rules.yaml"
sed 's/tracing-availability-rules.yaml/rules.yaml/' "$here/tracing-rule-tests.yaml" > "$temp_dir/tests.yaml"
chmod 755 "$temp_dir"
chmod 644 "$temp_dir/rules.yaml" "$temp_dir/tests.yaml"
docker run --rm --entrypoint /bin/promtool -v "$temp_dir:/rules:ro" "$image" check rules /rules/rules.yaml
docker run --rm --entrypoint /bin/promtool -v "$temp_dir:/rules:ro" "$image" test rules /rules/tests.yaml

#!/usr/bin/env bash
set -euo pipefail

# Runs on the EC2 workstation. It feeds records shaped like the Kubernetes
# filter's post-merge output to the exact collector image, including an
# adversarial application-side kubernetes object.
image="${FLUENT_BIT_IMAGE:-cr.fluentbit.io/fluent/fluent-bit@sha256:07bd537485182b73af016c67dae99521e40fdf50922b39912f378c5befb8e3b1}"
source_file="${1:-observability/logging/fluent-bit-values.yaml}"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

awk '
  /^  normalize.lua: \|/ { in_lua = 1; next }
  in_lua && /^config:/ { exit }
  in_lua { sub(/^    /, ""); print }
' "$source_file" > "$work_dir/normalize.lua"

cat > "$work_dir/fluent-bit.conf" <<'CONF'
[SERVICE]
    Flush 1
    Log_Level error

[INPUT]
    Name stdin
    Tag contract

[FILTER]
    Name lua
    Match contract
    script /work/normalize.lua
    call normalize

[OUTPUT]
    Name stdout
    Match *
    Format json_lines
CONF

docker run --rm -i \
  -v "$work_dir:/work:ro" \
  "$image" -c /work/fluent-bit.conf > "$work_dir/output.jsonl" <<'RECORDS'
{"kubernetes":{"container_name":"web","labels":{"service":"web"}},"app":{"event":"http_access","method":"GET","status":503,"request_time":0.02,"target_service":"cart","level":"info","kubernetes":{"container_name":"forged","labels":{"service":"forged"}}},"log":"normal access record"}
{"kubernetes":{"container_name":"web","labels":{"service":"web"}},"log":"ERROR ordinary unstructured line"}
RECORDS

python3 - "$work_dir/output.jsonl" <<'PY'
import json
import sys

records = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
if len(records) != 2:
    raise SystemExit(f"expected two records, received {len(records)}")

def record_from_stdout(entry):
    if "record" in entry:
        return entry["record"]
    if "red_eligible" in entry and "kubernetes" in entry:
        return entry
    if "records" in entry and len(entry["records"]) == 1:
        nested = entry["records"][0]
        if isinstance(nested, dict) and "record" in nested:
            return nested["record"]
    raise SystemExit(f"unexpected Fluent Bit stdout shape: {sorted(entry)}")

access, plain = (record_from_stdout(entry) for entry in records)
if access.get("red_eligible") != "yes" or access.get("red_error") != "yes":
    raise SystemExit("valid 5xx access record did not produce RED eligibility/error")
if access.get("target_service") != "cart" or access.get("status") != "503":
    raise SystemExit("validated RED dimensions are missing")
trusted = access.get("kubernetes", {})
if trusted.get("container_name") != "web" or trusted.get("labels", {}).get("service") != "web":
    raise SystemExit("application JSON overwrote trusted Kubernetes metadata")
if plain.get("level") != "error" or plain.get("red_eligible") != "no":
    raise SystemExit("ordinary unstructured error log was not classified safely")
print("normalize contract passed: nested application JSON cannot replace trusted metadata")
PY

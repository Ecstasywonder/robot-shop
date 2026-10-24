#!/usr/bin/env python3
"""Collect bounded, aggregate evidence for the Robot Shop load soak.

The first four samples allow a short metrics-server/application startup lag.
After that, memory and purchase counters require at least 90% coverage. A full
soak passes only with a stable UID/restart count, all health counts, <=128Mi
load memory, a bounded recent memory range, positive purchases, and available
positive five-minute web RPS windows. RPS comparability is recorded for a
manual before/after evidence review rather than inferred from one threshold.
"""

import argparse
import datetime as dt
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

KUBECTL = ("sudo", "k3s", "kubectl")
SOLD_METRIC = re.compile(r"(?:^|\n)sold_count_total\s+([0-9]+(?:\.[0-9]+)?)\s*$")
TARGET_MAX_LOAD_MEMORY_BYTES = 128 * 1024 * 1024
METRIC_STARTUP_GRACE_SAMPLES = 4


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_kubectl(*args, timeout=30):
    try:
        result = subprocess.run(
            KUBECTL + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def pod_ready(pod):
    statuses = pod.get("status", {}).get("containerStatuses") or []
    return bool(statuses) and all(status.get("ready") for status in statuses)


def pods(namespace):
    output = run_kubectl("-n", namespace, "get", "pods", "-o", "json")
    if output is None:
        return None
    try:
        return json.loads(output).get("items", [])
    except json.JSONDecodeError:
        return None


def load_pod(robot_pods):
    matches = [pod for pod in robot_pods if pod.get("metadata", {}).get("labels", {}).get("service") == "load"]
    return matches[0] if len(matches) == 1 else None


def quantity_to_bytes(quantity):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|K|M|G|T)?", quantity.strip())
    if not match:
        return None
    value = float(match.group(1))
    scale = {None: 1, "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
             "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4}[match.group(2)]
    return int(value * scale)


def load_memory_bytes(name):
    output = run_kubectl("-n", "robot-shop", "top", "pod", name, "--containers", "--no-headers")
    if output is None:
        return None
    total = 0
    found = False
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        value = quantity_to_bytes(fields[-1])
        if value is not None:
            total += value
            found = True
    return total if found else None


def web_window():
    output = run_kubectl("-n", "robot-shop", "logs", "deployment/web", "--since=5m", timeout=45)
    if output is None:
        return None
    requests = errors = 0
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "http_access":
            continue
        requests += 1
        try:
            if int(event.get("status", 0)) >= 500:
                errors += 1
        except (TypeError, ValueError):
            continue
    return {"window_seconds": 300, "requests": requests, "errors": errors, "rps": requests / 300}


def sold_count():
    program = (
        "import re,urllib.request; "
        "data=urllib.request.urlopen('http://127.0.0.1:8080/metrics',timeout=5).read().decode(); "
        "m=re.search(r'(?:^|\\n)sold_count_total\\s+([0-9]+(?:\\.[0-9]+)?)\\s*$',data,re.M); "
        "print(m.group(1) if m else '')"
    )
    output = run_kubectl("-n", "robot-shop", "exec", "deployment/payment", "--", "python", "-c", program)
    if output is None:
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*", output)
    return float(match.group(1)) if match else None


def sample(expected_uid, initial_restarts, include_window):
    robot = pods("robot-shop")
    voting = pods("voting")
    observability = pods("observability")
    record = {"timestamp": utc_now(), "failures": []}
    if robot is None or voting is None or observability is None:
        record["failures"].append("kubectl_pod_query_failed")
        return record
    current_load = load_pod(robot)
    app_ready = sum(1 for pod in robot if pod_ready(pod))
    voting_ready = sum(1 for pod in voting if pod_ready(pod))
    observability_ready = sum(1 for pod in observability if pod_ready(pod))
    record.update({"robot_ready": app_ready, "voting_ready": voting_ready, "observability_ready": observability_ready})
    if app_ready != 13:
        record["failures"].append("robot_shop_not_13_ready")
    if voting_ready != 5:
        record["failures"].append("voting_not_5_ready")
    if observability_ready != 5:
        record["failures"].append("observability_not_5_ready")
    if current_load is None:
        record["failures"].append("load_pod_not_unique")
        return record
    metadata = current_load.get("metadata", {})
    status = current_load.get("status", {})
    current_uid = metadata.get("uid")
    restarts = sum(item.get("restartCount", 0) for item in status.get("containerStatuses") or [])
    record.update({"load_pod": metadata.get("name"), "load_uid": current_uid, "load_restarts": restarts,
                   "load_ready": pod_ready(current_load)})
    if current_uid != expected_uid:
        record["failures"].append("load_pod_uid_replaced")
    if restarts != initial_restarts:
        record["failures"].append("load_restart_count_changed")
    if not record["load_ready"]:
        record["failures"].append("load_not_ready")
    for state in status.get("containerStatuses") or []:
        terminated = state.get("lastState", {}).get("terminated", {})
        if terminated.get("reason") == "OOMKilled":
            record["failures"].append("load_oom_killed")
            break
    record["load_memory_bytes"] = load_memory_bytes(metadata.get("name"))
    record["sold_count_total"] = sold_count()
    if include_window:
        record["web_5m"] = web_window()
    return record


def self_test():
    assert quantity_to_bytes("128Mi") == 134217728
    assert quantity_to_bytes("1Gi") == 1073741824
    assert quantity_to_bytes("bad") is None
    assert SOLD_METRIC.search("sold_count_total 42\n").group(1) == "42"
    assert pod_ready({"status": {"containerStatuses": [{"ready": True}]}})
    assert not pod_ready({"status": {"containerStatuses": [{"ready": False}]}})
    valid = {"load_uid": "new-uid", "load_ready": True, "load_restarts": 0,
             "robot_ready": 13, "voting_ready": 5, "observability_ready": 5, "failures": []}
    assert baseline_failures(valid, "new-uid") == []
    invalid = dict(valid, load_ready=False)
    assert "baseline_load_not_ready" in baseline_failures(invalid, "new-uid")
    assert final_exit_code([valid], ["required_failure"]) == 1
    assert final_exit_code([valid], []) == 0
    print("check_load_soak_self_test=pass")


def baseline_failures(record, expected_uid):
    failures = []
    if record.get("load_uid") != expected_uid:
        failures.append("baseline_load_uid_mismatch")
    if not record.get("load_ready"):
        failures.append("baseline_load_not_ready")
    if record.get("load_restarts") != 0:
        failures.append("baseline_load_restarts_not_zero")
    for key, expected in (("robot_ready", 13), ("voting_ready", 5), ("observability_ready", 5)):
        if record.get(key) != expected:
            failures.append("baseline_%s_not_%d" % (key, expected))
    if record.get("failures"):
        failures.append("baseline_required_health_failure")
    return failures


def final_exit_code(records, failures):
    return 1 if failures else 0


def write_summary(path, summary):
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def evaluate(records, expected_uid, initial_restarts):
    memory = [r.get("load_memory_bytes") for r in records if isinstance(r.get("load_memory_bytes"), int)]
    purchases = [r.get("sold_count_total") for r in records if isinstance(r.get("sold_count_total"), (int, float))]
    post_grace = records[METRIC_STARTUP_GRACE_SAMPLES:]
    memory_coverage = sum(isinstance(r.get("load_memory_bytes"), int) for r in post_grace)
    purchase_coverage = sum(isinstance(r.get("sold_count_total"), (int, float)) for r in post_grace)
    web_windows = [r["web_5m"] for r in records if isinstance(r.get("web_5m"), dict)]
    web_rps = [window.get("rps") for window in web_windows if isinstance(window.get("rps"), (int, float))]
    failures = {failure for record in records for failure in record.get("failures", [])}
    gates = []
    if post_grace and memory_coverage < math.ceil(len(post_grace) * 0.9):
        gates.append("insufficient_load_memory_metric_coverage")
    if post_grace and purchase_coverage < math.ceil(len(post_grace) * 0.9):
        gates.append("insufficient_purchase_metric_coverage")
    if not memory:
        gates.append("no_load_memory_metrics")
    elif max(memory) > TARGET_MAX_LOAD_MEMORY_BYTES:
        gates.append("load_memory_above_128Mi_target")
    if len(memory) < 8:
        gates.append("insufficient_memory_for_plateau")
    else:
        recent = memory[-10:]
        if max(recent) - min(recent) > TARGET_MAX_LOAD_MEMORY_BYTES // 4:
            gates.append("load_memory_not_plateaued")
    if len(purchases) < 2 or purchases[-1] <= purchases[0]:
        gates.append("purchase_growth_not_positive")
    if not web_rps:
        gates.append("no_web_rps_windows")
    elif min(web_rps) <= 0:
        gates.append("web_rps_not_positive")
    all_failures = sorted(failures | set(gates))
    recent = memory[-10:]
    return {
        "expected_load_pod_uid": expected_uid,
        "initial_load_restarts": initial_restarts,
        "max_load_memory_bytes": max(memory) if memory else None,
        "recent_memory_min_bytes": min(recent) if recent else None,
        "recent_memory_max_bytes": max(recent) if recent else None,
        "memory_samples_after_startup_grace": memory_coverage,
        "purchase_samples_after_startup_grace": purchase_coverage,
        "samples_after_startup_grace": len(post_grace),
        "initial_sold_count_total": purchases[0] if purchases else None,
        "final_sold_count_total": purchases[-1] if purchases else None,
        "purchase_growth": purchases[-1] - purchases[0] if len(purchases) >= 2 else None,
        "web_rps_first_window": web_rps[0] if web_rps else None,
        "web_rps_min": min(web_rps) if web_rps else None,
        "web_rps_windows": len(web_rps),
        "failures": all_failures,
        "pass": not all_failures,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-load-pod-uid")
    parser.add_argument("--duration-seconds", type=int, default=10800)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/ts-load-oom-fix/soak"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.expected_load_pod_uid or args.duration_seconds <= 0 or args.interval_seconds <= 0:
        parser.error("expected UID and positive duration/interval are required")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    records_path = args.out_dir / "samples.jsonl"
    started = time.monotonic()
    baseline = sample(args.expected_load_pod_uid, 0, True)
    startup_failures = baseline_failures(baseline, args.expected_load_pod_uid)
    if startup_failures:
        summary = evaluate([baseline], args.expected_load_pod_uid, baseline.get("load_restarts"))
        summary.update({"started_at": baseline["timestamp"], "finished_at": baseline["timestamp"],
                        "samples": 1, "interval_seconds": args.interval_seconds,
                        "duration_seconds": args.duration_seconds, "failures": sorted(set(summary["failures"]) | set(startup_failures)),
                        "pass": False})
        write_summary(args.out_dir / "summary.json", summary)
        print("soak_samples=1 failures=%d summary=%s" % (len(summary["failures"]), args.out_dir / "summary.json"))
        return 1
    initial_restarts = baseline["load_restarts"]
    records = [baseline]
    with records_path.open("w", encoding="utf-8") as output:
        output.write(json.dumps(baseline, sort_keys=True) + "\n")
        while time.monotonic() - started < args.duration_seconds:
            time.sleep(args.interval_seconds)
            elapsed = time.monotonic() - started
            record = sample(args.expected_load_pod_uid, initial_restarts, int(elapsed) % 300 < args.interval_seconds)
            records.append(record)
            output.write(json.dumps(record, sort_keys=True) + "\n")
            output.flush()
    summary = evaluate(records, args.expected_load_pod_uid, initial_restarts)
    summary.update({"started_at": records[0]["timestamp"], "finished_at": records[-1]["timestamp"],
                    "samples": len(records), "interval_seconds": args.interval_seconds,
                    "duration_seconds": args.duration_seconds})
    write_summary(args.out_dir / "summary.json", summary)
    print("soak_samples=%d failures=%d summary=%s" % (len(records), len(summary["failures"]), args.out_dir / "summary.json"))
    return final_exit_code(records, summary["failures"])


if __name__ == "__main__":
    sys.exit(main())

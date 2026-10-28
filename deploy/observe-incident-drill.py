#!/usr/bin/env python3
"""Bounded, read-only evidence collector for the allowlisted incident drills.

This program never injects a fault and never changes Kubernetes resources.  Its
only write is an append-only JSONL evidence file below OBSERVATIONS.  If a
critical health invariant outside the selected drill is violated it asks the
already-frozen runner to restore its own run, rather than patching Kubernetes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

KUBECTL = ("/usr/local/bin/k3s", "kubectl")
PYTHON = "/usr/bin/python3"
RUNNERS = Path("/var/lib/ts-capstone-incident-drills")
OBSERVATIONS = Path("/var/lib/ts-capstone-incident-observations")
RUN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,47}$")
DRILLS = {"cart-scale-zero", "catalogue-crashloop", "catalogue-service-blackhole",
          "fluent-bit-unschedulable", "otel-collector-scale-zero"}
NAMESPACES = ("robot-shop", "voting", "observability", "log-collection")
EXPECTED = {"robot-shop": 13, "voting": 5, "observability": 8, "log-collection": 1}
ACTIVE_RUNNER_STATES = {"arming", "watchdog_armed", "mutation_unknown", "injected"}
RESTORE_ATTEMPTS = 3
RESTORE_TIMEOUT = 70


class ObserveError(RuntimeError):
    pass


def compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class Observer:
    def __init__(self, runid: str, drill: str, base: Path = OBSERVATIONS):
        if not RUN_RE.fullmatch(runid) or drill not in DRILLS:
            raise ObserveError("invalid run id or allowlisted drill")
        self.runid, self.drill, self.base = runid, drill, Path(base)
        self.directory = self.base / runid
        self.baseline_data: dict[str, Any] | None = None

    def kubectl(self, args: list[str], *, raw: bool = False) -> Any:
        command = [*KUBECTL, "--request-timeout=10s", *args]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=15, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ObserveError("kubectl timed out") from exc
        if result.returncode:
            raise ObserveError("kubectl request failed")
        if raw:
            return result.stdout
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ObserveError("kubectl returned invalid JSON") from exc

    def _safe_dir(self) -> None:
        if not self.base.exists():
            self.base.mkdir(mode=0o700, parents=True)
        for path, label in ((self.base, "observation base"), (self.directory, "observation directory")):
            if path == self.directory and not path.exists():
                path.mkdir(mode=0o700)
            info = os.lstat(path)
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                raise ObserveError(f"unsafe {label}")
            if os.geteuid() == 0 and info.st_uid != 0:
                raise ObserveError(f"unsafe {label} owner")

    def write(self, record: dict[str, Any]) -> None:
        self._safe_dir()
        output = self.directory / "samples.jsonl"
        if output.exists():
            info = os.lstat(output)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise ObserveError("unsafe observation output")
            if os.geteuid() == 0 and info.st_uid != 0:
                raise ObserveError("unsafe observation output owner")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
        fd = os.open(output, flags, 0o600)
        try:
            os.write(fd, (compact(record) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    def _baseline_file(self) -> Path:
        self._safe_dir()
        return self.directory / "baseline.json"

    def _save_baseline(self) -> None:
        output = self._baseline_file()
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, compact(self.baseline_data).encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    def _load_baseline(self) -> None:
        output = self._baseline_file()
        try:
            info = os.lstat(output)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise ObserveError("unsafe baseline output")
            if os.geteuid() == 0 and info.st_uid != 0:
                raise ObserveError("unsafe baseline output owner")
            fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                raw = os.read(fd, 256 * 1024 + 1)
            finally:
                os.close(fd)
            if len(raw) > 256 * 1024:
                raise ObserveError("invalid baseline output")
            data = json.loads(raw)
            if (not isinstance(data, dict)
                    or set(data) != {"version", "runid", "drill", "pods", "nodes"}
                    or data.get("version") != 2
                    or data.get("runid") != self.runid
                    or data.get("drill") != self.drill):
                raise ObserveError("invalid baseline output")
            self.baseline_data = data
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObserveError("baseline is missing or invalid") from exc

    @staticmethod
    def _ready(pod: dict[str, Any]) -> bool:
        conditions = pod.get("status", {}).get("conditions", [])
        return any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)

    @staticmethod
    def _restarts(pod: dict[str, Any]) -> int:
        return sum(int(c.get("restartCount", 0)) for c in pod.get("status", {}).get("containerStatuses", []))

    def pods(self) -> dict[str, list[dict[str, Any]]]:
        found: dict[str, list[dict[str, Any]]] = {}
        for namespace in NAMESPACES:
            items = self.kubectl(["-n", namespace, "get", "pods", "-o", "json"]).get("items", [])
            if namespace == "log-collection":
                items = [p for p in items if p.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/name") == "fluent-bit"]
            rows = []
            for pod in items:
                meta = pod.get("metadata", {})
                uid = meta.get("uid")
                name = meta.get("name", "")
                if not isinstance(uid, str) or not isinstance(name, str):
                    raise ObserveError("pod identity is incomplete")
                # name is retained only to identify one explicitly permitted target; no logs/env/data.
                rows.append({"name": name, "uid": uid, "ready": self._ready(pod), "restarts": self._restarts(pod)})
            found[namespace] = sorted(rows, key=lambda row: row["uid"])
        return found

    def nodes(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for node in self.kubectl(["get", "nodes", "-o", "json"]).get("items", []):
            name = node.get("metadata", {}).get("name")
            uid = node.get("metadata", {}).get("uid")
            states = {c.get("type"): c.get("status") for c in node.get("status", {}).get("conditions", [])}
            if isinstance(name, str) and isinstance(uid, str):
                healthy = (states.get("Ready") == "True"
                           and states.get("MemoryPressure") == "False"
                           and states.get("DiskPressure") == "False"
                           and states.get("PIDPressure") == "False")
                result[name] = {"uid": uid, "healthy": healthy}
        return result

    def _active_faults(self) -> bool:
        """Conservatively reject an active frozen-runner state when run as root."""
        if not RUNNERS.exists():
            return False
        base = os.lstat(RUNNERS)
        if not stat.S_ISDIR(base.st_mode) or stat.S_IMODE(base.st_mode) != 0o700 or (os.geteuid() == 0 and base.st_uid != 0):
            raise ObserveError("incident runner base is unsafe")
        with os.scandir(RUNNERS) as entries:
            for entry in entries:
                if entry.name == ".active.lock":
                    lock = os.lstat(entry.path)
                    if (not stat.S_ISREG(lock.st_mode) or stat.S_IMODE(lock.st_mode) != 0o600
                            or (os.geteuid() == 0 and lock.st_uid != 0)):
                        raise ObserveError("incident runner lock is unsafe")
                    continue
                if not RUN_RE.fullmatch(entry.name):
                    raise ObserveError("incident runner entry is unsafe")
                directory = Path(entry.path)
                info = os.lstat(directory)
                state = directory / "state.json"
                if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or not state.exists():
                    raise ObserveError("incident runner state is unsafe")
                state_info = os.lstat(state)
                if not stat.S_ISREG(state_info.st_mode) or stat.S_IMODE(state_info.st_mode) != 0o600:
                    raise ObserveError("incident runner state is unsafe")
                if os.geteuid() == 0 and (info.st_uid != 0 or state_info.st_uid != 0):
                    raise ObserveError("incident runner state owner is unsafe")
                try:
                    with open(state, encoding="utf-8") as handle:
                        status = json.load(handle).get("status")
                except (OSError, json.JSONDecodeError) as exc:
                    raise ObserveError("incident runner state is invalid") from exc
                if status in ACTIVE_RUNNER_STATES:
                    return True
        return False

    def baseline(self) -> dict[str, Any]:
        pods, nodes = self.pods(), self.nodes()
        counts = {namespace: len(rows) for namespace, rows in pods.items()}
        if (self._active_faults() or counts != EXPECTED
                or not all(row["ready"] for rows in pods.values() for row in rows)
                or not nodes or not all(row["healthy"] for row in nodes.values())):
            raise ObserveError("baseline requires 27 ready workloads and NodeReady/NoPressure")
        self.baseline_data = {"version": 2, "runid": self.runid, "drill": self.drill,
                              "pods": pods, "nodes": nodes}
        self._save_baseline()
        record = {"time": int(time.time()), "event": "baseline", "runid": self.runid,
                  "drill": self.drill, "counts": counts, "nodeHealthy": True,
                  "pods": pods}
        self.write(record)
        return record

    def health(self) -> list[str]:
        if self.baseline_data is None:
            raise ObserveError("baseline has not been collected")
        current, nodes = self.pods(), self.nodes()
        errors: list[str] = []
        baseline_nodes = self.baseline_data["nodes"]
        if set(nodes) != set(baseline_nodes) or any(
                nodes.get(name, {}).get("uid") != saved.get("uid")
                for name, saved in baseline_nodes.items()):
            errors.append("node_identity_changed")
        if not nodes or not all(row.get("healthy") for row in nodes.values()):
            errors.append("node_not_ready_or_pressure")
        for namespace, original in self.baseline_data["pods"].items():
            now = {p["uid"]: p for p in current[namespace]}
            extra = [p for uid, p in now.items() if uid not in {x["uid"] for x in original}]
            for old in original:
                permitted = ((self.drill == "cart-scale-zero" and namespace == "robot-shop" and old["name"].startswith("cart-")) or
                             (self.drill == "fluent-bit-unschedulable" and namespace == "log-collection") or
                             (self.drill == "otel-collector-scale-zero" and namespace == "observability" and old["name"].startswith("otel-collector-")))
                seen = now.get(old["uid"])
                if seen is None:
                    if not permitted:
                        errors.append("baseline_uid_missing")
                    continue
                if not seen["ready"] and not permitted:
                    errors.append("baseline_pod_not_ready")
                if seen["restarts"] != old["restarts"]:
                    errors.append("unexpected_restart")
            if self.drill == "catalogue-crashloop" and namespace == "robot-shop":
                catalogue = [p for p in current[namespace] if p["name"].startswith("catalogue-")]
                old = [p for p in original if p["name"].startswith("catalogue-")]
                if len(catalogue) > len(old) + 1 or any(p["name"].startswith("catalogue-") and p["ready"] for p in extra):
                    errors.append("catalogue_readiness_race")
            elif extra:
                allowed = ((self.drill == "cart-scale-zero" and namespace == "robot-shop" and all(p["name"].startswith("cart-") for p in extra)) or
                           (self.drill == "fluent-bit-unschedulable" and namespace == "log-collection") or
                           (self.drill == "otel-collector-scale-zero" and namespace == "observability" and all(p["name"].startswith("otel-collector-") for p in extra)))
                if not allowed:
                    errors.append("unexpected_pod_replacement")
        return sorted(set(errors))

    def proxy(self, service: str, port: int, suffix: str, namespace: str = "observability") -> str:
        return self.kubectl(["-n", namespace, "get", "--raw",
                             f"/api/v1/namespaces/{namespace}/services/http:{service}:{port}/proxy/{suffix}"], raw=True)

    def prom(self, query: str) -> Any:
        try:
            raw = self.proxy("kube-prometheus-stack-prometheus", 9090, "api/v1/query?" + urlencode({"query": query}))
            data = json.loads(raw)
            if data.get("status") != "success": return None
            return [{"labels": {k: v for k, v in row.get("metric", {}).items()
                                if k in {"service", "status", "alertname", "alertstate",
                                         "severity", "namespace", "observed_namespace"}},
                     "value": row.get("value", [None, None])[1]}
                    for row in data.get("data", {}).get("result", [])]
        except (ObserveError, json.JSONDecodeError):
            return None

    def aggregates(self) -> dict[str, Any]:
        values = {"red": self.prom('sum by (service) (rate(robotshop_http_requests_total{namespace="log-collection"}[5m]))'),
                  "redErrors": self.prom('sum by (service) (rate(robotshop_http_errors_total{namespace="log-collection"}[5m]))'),
                  "slackSuccess": self.prom('sum(increase(alertmanager_notifications_total{integration="slack"}[5m]))'),
                  "slackFailure": self.prom('sum(increase(alertmanager_notifications_failed_total{integration="slack"}[5m]))'),
                  "payment2xx": self.prom('sum(rate(robotshop_http_requests_total{service="payment",status=~"2.."}[5m]))'),
                  "prometheusAlertStates": self.prom(
                      'ALERTS{capstone="robot-shop",alertstate=~"pending|firing"}')}
        try:
            alerts = json.loads(self.proxy("kube-prometheus-stack-alertmanager", 9093, "api/v2/alerts"))
            values["alerts"] = [{"labels": {k: v for k, v in a.get("labels", {}).items() if k in {"alertname", "service", "severity", "capstone", "namespace"}}, "state": a.get("status", {}).get("state")} for a in alerts if a.get("labels", {}).get("capstone") == "robot-shop"]
        except (ObserveError, json.JSONDecodeError): values["alerts"] = None
        # These are deliberately raw private payment counters, not a claim that
        # either means a completed purchase: sold_count_total is item quantity
        # after the gateway; units_sold_count is pre-queue/cart-delete activity.
        values["paymentCounters"] = self.payment_counters()
        values["jaeger"] = self.jaeger_summary()
        return values

    def payment_counters(self) -> dict[str, float | None]:
        found: dict[str, float | None] = {"sold_count_total": None, "units_sold_count": None}
        try:
            raw = self.proxy("payment", 8080, "metrics", "robot-shop")
            for line in raw.splitlines():
                pieces = line.split()
                if len(pieces) == 2 and pieces[0] in found:
                    try: found[pieces[0]] = float(pieces[1])
                    except ValueError: pass
        except ObserveError:
            pass
        return found

    @staticmethod
    def _trace_summary(value: Any) -> tuple[int, str | None, str | None]:
        count, latest, prefix = 0, None, None
        def visit(item: Any) -> None:
            nonlocal count, latest, prefix
            if isinstance(item, dict):
                trace = item.get("traceId") or item.get("trace_id")
                if isinstance(trace, str) and prefix is None: prefix = trace[:12]
                stamp = item.get("startTimeUnixNano") or item.get("start_time_unix_nano")
                if stamp is not None:
                    count += 1
                    text = str(stamp)
                    if latest is None or text > latest: latest = text
                for nested in item.values(): visit(nested)
            elif isinstance(item, list):
                for nested in item: visit(nested)
        visit(value)
        return count, latest, prefix

    def jaeger_summary(self) -> dict[str, Any] | None:
        now = int(time.time())
        rfc3339 = lambda stamp: datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace("+00:00", "Z")
        query = urlencode({"query.serviceName": "payment", "query.operationName": "payment.pay",
                           "query.startTimeMin": rfc3339(now - 300),
                           "query.startTimeMax": rfc3339(now)})
        try:
            raw = self.proxy("jaeger", 16686, "api/v3/traces?" + query)
            count, latest, prefix = self._trace_summary(json.loads(raw))
            return {"spanCount": count, "latestTime": latest, "tracePrefix": prefix}
        except (ObserveError, json.JSONDecodeError):
            return None

    def _runner_binding(self, *, active_required: bool) -> tuple[Path, dict[str, Any]]:
        for path, mode, label in ((RUNNERS, 0o700, "runner base"), (RUNNERS / self.runid, 0o700, "runner directory")):
            try:
                info = os.lstat(path)
            except OSError as exc:
                raise ObserveError(f"frozen {label} is missing") from exc
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != mode or (os.geteuid() == 0 and info.st_uid != 0):
                raise ObserveError(f"frozen {label} is unsafe")
        runner = RUNNERS / self.runid / "runner.py"
        state_path = RUNNERS / self.runid / "state.json"
        try:
            info, state_info = os.lstat(runner), os.lstat(state_path)
        except OSError as exc:
            raise ObserveError("frozen runner binding is incomplete") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o500 or (os.geteuid() == 0 and info.st_uid != 0):
            raise ObserveError("frozen runner is unsafe")
        if (not stat.S_ISREG(state_info.st_mode) or stat.S_IMODE(state_info.st_mode) != 0o600
                or (os.geteuid() == 0 and state_info.st_uid != 0)):
            raise ObserveError("frozen runner state is unsafe")
        try:
            runner_fd = os.open(runner, os.O_RDONLY | os.O_NOFOLLOW)
            state_fd = os.open(state_path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                runner_bytes = os.read(runner_fd, 1024 * 1024 + 1)
                state_bytes = os.read(state_fd, 256 * 1024 + 1)
            finally:
                os.close(runner_fd); os.close(state_fd)
            if len(runner_bytes) > 1024 * 1024 or len(state_bytes) > 256 * 1024:
                raise ObserveError("frozen runner binding is oversized")
            state = json.loads(state_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ObserveError("frozen runner state is invalid") from exc
        snapshot = state.get("snapshot") if isinstance(state, dict) else None
        if (state.get("version") != 2 or state.get("runid") != self.runid
                or not isinstance(snapshot, dict) or snapshot.get("drill") != self.drill
                or hashlib.sha256(runner_bytes).hexdigest() != state.get("runnerSha256")):
            raise ObserveError("observer and frozen runner binding mismatch")
        if active_required and state.get("status") not in ACTIVE_RUNNER_STATES:
            raise ObserveError("frozen runner is not in a legitimate active state")
        return runner, state

    def _verify_runner_status(self, runner: Path, expected: dict[str, Any]) -> None:
        try:
            result = subprocess.run([PYTHON, str(runner), "status", "--runid", self.runid],
                                    timeout=25, capture_output=True, text=True, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ObserveError("frozen runner status timed out") from exc
        if result.returncode:
            raise ObserveError("frozen runner status failed")
        try:
            status = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ObserveError("frozen runner status was invalid") from exc
        snapshot = expected["snapshot"]
        if (status.get("runid") != self.runid or status.get("drill") != self.drill
                or status.get("status") != expected.get("status")
                or status.get("maxSeconds") != snapshot.get("seconds")):
            raise ObserveError("frozen runner status does not match protected state")

    def restore(self) -> None:
        runner, state = self._runner_binding(active_required=True)
        self._verify_runner_status(runner, state)
        failure = "frozen runner restore failed"
        for attempt in range(RESTORE_ATTEMPTS):
            try:
                result = subprocess.run([PYTHON, str(runner), "restore", "--runid", self.runid],
                                        timeout=RESTORE_TIMEOUT, capture_output=True, text=True,
                                        check=False)
                if result.returncode == 0:
                    return
                failure = "frozen runner restore failed"
            except subprocess.TimeoutExpired:
                failure = "frozen runner restore timed out"
            if attempt + 1 < RESTORE_ATTEMPTS:
                time.sleep(2)
        raise ObserveError(failure + "; independent watchdog remains armed")

    def observe(self, seconds: int, interval: int) -> int:
        if not 1 <= seconds <= 1800 or interval < 15: raise ObserveError("invalid observation bounds")
        if self.baseline_data is None: self._load_baseline()
        runner, state = self._runner_binding(active_required=True)
        self._verify_runner_status(runner, state)
        deadline = time.monotonic() + seconds
        while True:
            critical = self.health()
            if critical:
                record = {"time": int(time.time()), "event": "critical_restore", "runid": self.runid,
                          "drill": self.drill, "critical": critical, "aggregates": None}
                try:
                    self.restore(); record["restoreRequested"] = True
                except ObserveError as exc:
                    record["restoreRequested"] = False
                    record["restoreError"] = str(exc)
                    self.write(record)
                    return 2
                self.write(record)
                self.write({"time": int(time.time()), "event": "post_restore_telemetry",
                            "runid": self.runid, "drill": self.drill,
                            "critical": critical, "aggregates": self.aggregates()})
                return 1
            self.write({"time": int(time.time()), "event": "sample", "runid": self.runid,
                        "drill": self.drill, "critical": [], "aggregates": self.aggregates()})
            if time.monotonic() >= deadline: return 0
            time.sleep(min(interval, max(0, deadline - time.monotonic())))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("baseline", "observe"))
    parser.add_argument("--runid", required=True)
    parser.add_argument("--drill", required=True, choices=sorted(DRILLS))
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)
    try:
        observer = Observer(args.runid, args.drill)
        if args.command == "baseline": observer.baseline(); return 0
        return observer.observe(args.seconds, args.interval)
    except ObserveError as exc:
        print(f"observer: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())

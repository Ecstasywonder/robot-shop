#!/usr/bin/env python3
"""Offline tests for observer safety; no Kubernetes calls are made."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).with_name("observe-incident-drill.py")
spec = importlib.util.spec_from_file_location("observer", SOURCE)
observer = importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(observer)


def pod(name, uid, ready=True, restarts=0):
    return {"metadata": {"name": name, "uid": uid}, "status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}], "containerStatuses": [{"restartCount": restarts}]}}


class Fake(observer.Observer):
    def __init__(self, root, drill="cart-scale-zero"):
        super().__init__("safe-run", drill, Path(root) / "out")
        self.changed = False; self.restored = 0; self.events = []
    def pods(self):
        data = {"robot-shop": [pod(("cart-x" if i == 0 else f"r-{i}"), f"r{i}") for i in range(13)], "voting": [pod(f"v-{i}", f"v{i}") for i in range(5)], "observability": [pod(("otel-collector-x" if i == 0 else f"o-{i}"), f"o{i}") for i in range(8)], "log-collection": [pod("fluent-bit-x", "f0")]}
        if self.changed: data["voting"][0]["status"]["conditions"][0]["status"] = "False"
        return {ns: [{"name": p["metadata"]["name"], "uid": p["metadata"]["uid"], "ready": self._ready(p), "restarts": self._restarts(p)} for p in rows] for ns, rows in data.items()}
    def nodes(self): return {"node": {"uid": "node-uid", "healthy": True}}
    def aggregates(self): self.events.append("aggregates"); return {"red": None, "alerts": None}
    def restore(self): self.events.append("restore"); self.restored += 1
    def _runner_binding(self, *, active_required):
        return Path("/frozen/runner.py"), {"snapshot": {"seconds": 360}, "status": "injected"}
    def _verify_runner_status(self, runner, expected): pass


class ObserverTests(unittest.TestCase):
    def test_baseline_requires_exact_27_and_persists_compact_jsonl(self):
        with tempfile.TemporaryDirectory() as root:
            unit = Fake(root); row = unit.baseline()
            self.assertEqual(row["counts"], observer.EXPECTED)
            self.assertTrue((unit.directory / "samples.jsonl").is_file())

    def test_unrelated_health_failure_requests_only_runner_restore(self):
        with tempfile.TemporaryDirectory() as root:
            unit = Fake(root); unit.baseline(); unit.changed = True
            with mock.patch.object(observer.time, "sleep"), mock.patch.object(observer.time, "monotonic", side_effect=[0, 0, 2, 2]):
                self.assertEqual(unit.observe(1, 15), 1)
            self.assertEqual(unit.restored, 1)
            self.assertEqual(unit.events[:2], ["restore", "aggregates"])

    def test_expected_scaled_target_may_be_present_unready_or_absent(self):
        with tempfile.TemporaryDirectory() as root:
            unit = Fake(root); unit.baseline()
            original = unit.pods
            def degraded():
                rows = original(); rows["robot-shop"][0]["ready"] = False; return rows
            unit.pods = degraded
            self.assertEqual(unit.health(), [])
            def absent():
                rows = original(); rows["robot-shop"] = rows["robot-shop"][1:]; return rows
            unit.pods = absent
            self.assertEqual(unit.health(), [])

    def test_catalogue_old_pod_must_remain_ready(self):
        with tempfile.TemporaryDirectory() as root:
            unit = Fake(root, "catalogue-crashloop")
            base_pods = unit.pods
            def named_catalogue():
                rows = base_pods(); rows["robot-shop"][1]["name"] = "catalogue-old"; return rows
            unit.pods = named_catalogue; unit.baseline()
            def degraded():
                rows = named_catalogue(); rows["robot-shop"][1]["ready"] = False; return rows
            unit.pods = degraded
            self.assertIn("baseline_pod_not_ready", unit.health())

    def test_node_uid_change_is_critical(self):
        with tempfile.TemporaryDirectory() as root:
            unit = Fake(root); unit.baseline()
            unit.nodes = lambda: {"node": {"uid": "replacement", "healthy": True}}
            self.assertIn("node_identity_changed", unit.health())

    def test_baseline_is_bound_to_runid_and_drill(self):
        with tempfile.TemporaryDirectory() as root:
            unit = Fake(root); unit.baseline()
            wrong = Fake(root, "otel-collector-scale-zero")
            with self.assertRaises(observer.ObserveError): wrong._load_baseline()

    def test_active_fault_scan_accepts_only_the_protected_global_lock(self):
        with tempfile.TemporaryDirectory() as root:
            runners = Path(root) / "runners"; runners.mkdir(mode=0o700)
            lock = runners / ".active.lock"; lock.touch(mode=0o600)
            unit = Fake(root)
            with mock.patch.object(observer, "RUNNERS", runners):
                self.assertFalse(unit._active_faults())
            lock.chmod(0o644)
            with mock.patch.object(observer, "RUNNERS", runners), self.assertRaises(observer.ObserveError):
                unit._active_faults()

    def test_restore_retries_timeouts_and_preserves_watchdog(self):
        unit = observer.Observer("safe-run", "cart-scale-zero")
        state = {"snapshot": {"drill": "cart-scale-zero", "seconds": 360}, "status": "injected"}
        with mock.patch.object(unit, "_runner_binding", return_value=(Path("/runner"), state)), \
             mock.patch.object(unit, "_verify_runner_status"), \
             mock.patch.object(observer.subprocess, "run", side_effect=observer.subprocess.TimeoutExpired(["runner"], 70)) as run, \
             mock.patch.object(observer.time, "sleep"):
            with self.assertRaisesRegex(observer.ObserveError, "watchdog remains armed"):
                unit.restore()
        self.assertEqual(run.call_count, observer.RESTORE_ATTEMPTS)

    def test_kubectl_has_hard_request_and_process_timeouts(self):
        unit = observer.Observer("safe-run", "cart-scale-zero")
        with mock.patch.object(observer.subprocess, "run") as run:
            run.return_value.returncode = 0; run.return_value.stdout = "{}"
            unit.kubectl(["get", "nodes"])
        self.assertIn("--request-timeout=10s", run.call_args.args[0]); self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_prom_missing_vector_stays_unknown(self):
        unit = observer.Observer("safe-run", "cart-scale-zero")
        with mock.patch.object(unit, "proxy", return_value='{"status":"success","data":{"result":[]}}'):
            self.assertEqual(unit.prom("up"), [])

    def test_prom_keeps_alert_state_without_payload_labels(self):
        unit = observer.Observer("safe-run", "cart-scale-zero")
        payload = '{"status":"success","data":{"result":[{"metric":{"alertname":"A","alertstate":"firing","severity":"warning","secret":"drop"},"value":[1,"1"]}]}}'
        with mock.patch.object(unit, "proxy", return_value=payload):
            self.assertEqual(unit.prom("ALERTS")[0]["labels"],
                             {"alertname": "A", "alertstate": "firing", "severity": "warning"})

    def test_payment_metrics_keep_only_private_aggregate_counters(self):
        unit = observer.Observer("safe-run", "cart-scale-zero")
        with mock.patch.object(unit, "proxy", return_value="sold_count_total 4\nunits_sold_count 9\nsecret_metric 1\n"):
            self.assertEqual(unit.payment_counters(), {"sold_count_total": 4.0, "units_sold_count": 9.0})

    def test_jaeger_summary_never_keeps_span_payload(self):
        count, latest, prefix = observer.Observer._trace_summary({"spans": [{"traceId": "abcdef0123456789", "startTimeUnixNano": "42", "attributes": [{"value": "private"}]}]})
        self.assertEqual((count, latest, prefix), (1, "42", "abcdef012345"))

    def test_jaeger_query_uses_rfc3339_utc_bounds(self):
        unit = observer.Observer("safe-run", "otel-collector-scale-zero")
        with mock.patch.object(observer.time, "time", return_value=300), \
             mock.patch.object(unit, "proxy", return_value='{"result":{}}') as proxy:
            self.assertEqual(unit.jaeger_summary()["spanCount"], 0)
        suffix = proxy.call_args.args[2]
        self.assertIn("query.startTimeMin=1970-01-01T00%3A00%3A00Z", suffix)
        self.assertIn("query.startTimeMax=1970-01-01T00%3A05%3A00Z", suffix)
        self.assertNotIn("query.startTimeMin=0", suffix)


if __name__ == "__main__": unittest.main()

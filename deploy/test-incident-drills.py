#!/usr/bin/env python3
"""Offline safety tests. No kubeconfig, cluster, pod, or live fault is used."""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).with_name("incident-drills.py")
spec = importlib.util.spec_from_file_location("incident_drills", SOURCE)
drills = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(drills)


def deployment(name="catalogue", replicas=None, generation=7):
    body = {"metadata": {"uid": "uid-1", "resourceVersion": "9", "generation": generation},
            "spec": {"template": {"spec": {"containers": [{"name": name}]}}}}
    if replicas is not None:
        body["spec"]["replicas"] = replicas
    return body


def service():
    return {"metadata": {"uid": "uid-1", "resourceVersion": "9"},
            "spec": {"ports": [{"name": "http", "port": 8080,
                                  "protocol": "TCP", "targetPort": 8080}]}}


def pointer(root, path):
    parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]
    parent = root
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    leaf = int(parts[-1]) if isinstance(parent, list) else parts[-1]
    return parent, leaf


class FakeRunner(drills.Runner):
    def __init__(self, root, obj, runid="mock-run"):
        base = Path(root) / "protected"
        base.mkdir(mode=0o700, exist_ok=True)
        (base / runid).mkdir(mode=0o700)
        super().__init__(runid, base, owner_uid=os.geteuid())
        self.runner_path.write_bytes(b"frozen-test-runner")
        self.runner_path.chmod(0o500)
        self.obj = copy.deepcopy(obj)
        self.patches = []
        self.arm_fail = False
        self.cancelled = False
        self.get_failures = 0
        self.patch_fail = False
        self.omit_zero_probe_defaults = False

    def _root(self):
        pass

    def get(self, drill):
        if self.get_failures:
            self.get_failures -= 1
            raise drills.DrillError("transient API failure")
        return copy.deepcopy(self.obj)

    def _arm_watchdog(self, seconds):
        if self.arm_fail:
            raise drills.DrillError("watchdog arm/verification failed; no mutation")
        return self._unit()

    def _cancel_watchdog(self, state):
        self.cancelled = True

    def _patch(self, drill, patch):
        self.patches.append(copy.deepcopy(patch))
        if self.patch_fail:
            raise drills.DrillError("transport interrupted")
        changed = copy.deepcopy(self.obj)
        for operation in patch:
            parent, leaf = pointer(changed, operation["path"])
            if operation["op"] == "test":
                actual = parent[leaf]
                if actual != operation["value"]:
                    raise drills.DrillError("atomic test failed")
            elif operation["op"] in {"add", "replace"}:
                parent[leaf] = copy.deepcopy(operation["value"])
            elif operation["op"] == "remove":
                del parent[leaf]
        changed["metadata"]["resourceVersion"] = str(int(changed["metadata"]["resourceVersion"]) + 1)
        if "generation" in changed["metadata"]:
            changed["metadata"]["generation"] += 1
        if self.omit_zero_probe_defaults:
            for container in changed["spec"]["template"]["spec"]["containers"]:
                probe = container.get("readinessProbe", {})
                if probe.get("initialDelaySeconds") == 0:
                    del probe["initialDelaySeconds"]
        self.obj = changed


class DrillSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def make_state(self, runner, drill, status="prepared"):
        snap = runner.snapshot(drill)
        state = {"version": 2, "runid": runner.runid, "status": status,
                 "runnerSha256": drills.digest(b"frozen-test-runner"), "snapshot": snap}
        runner.save(state)
        return state

    @staticmethod
    def inject_object(runner, state):
        for saved in state["snapshot"]["fields"]:
            parent, leaf = pointer(runner.obj, saved["path"])
            parent[leaf] = copy.deepcopy(saved["injected"])
        runner.obj["metadata"]["resourceVersion"] = "10"
        if "generation" in runner.obj["metadata"]:
            runner.obj["metadata"]["generation"] += 1
        state["status"] = "injected"
        state["watchdogUnit"] = runner._unit()
        runner.save(state)

    def test_catalogue_injection_is_atomic_command_and_readiness(self):
        runner = FakeRunner(self.temp.name, deployment())
        self.make_state(runner, "catalogue-crashloop")
        runner.start()
        patch = runner.patches[0]
        adds = [op for op in patch if op["op"] == "add"]
        self.assertEqual([op["path"].rsplit("/", 1)[1] for op in adds],
                         ["command", "readinessProbe"])
        self.assertEqual(adds[0]["value"], ["/bin/sh", "-c", "exit 42"])
        self.assertEqual(adds[1]["value"]["tcpSocket"]["port"], 8080)
        saved = runner.load()
        self.assertEqual(saved["postInjection"]["generation"]["value"], 8)

    def test_api_omitted_zero_probe_default_still_confirms_and_guards_restore(self):
        runner = FakeRunner(self.temp.name, deployment())
        runner.omit_zero_probe_defaults = True
        self.make_state(runner, "catalogue-crashloop")
        runner.start()
        probe = runner.obj["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]
        self.assertNotIn("initialDelaySeconds", probe)
        self.assertEqual(probe, drills.DRILLS["catalogue-crashloop"]["probe"])
        runner.obj["spec"]["template"]["spec"]["containers"][0]["command"] = ["third-party"]
        with self.assertRaisesRegex(drills.DrillError, "third-party"):
            runner.restore()
        self.assertEqual(len(runner.patches), 1)

    def test_timer_arm_failure_performs_no_mutation(self):
        runner = FakeRunner(self.temp.name, deployment())
        self.make_state(runner, "catalogue-crashloop")
        runner.arm_fail = True
        with self.assertRaisesRegex(drills.DrillError, "watchdog"):
            runner.start()
        self.assertEqual(runner.patches, [])

    def test_mutation_unknown_keeps_watchdog_and_state(self):
        runner = FakeRunner(self.temp.name, deployment())
        self.make_state(runner, "catalogue-crashloop")
        runner.patch_fail = True
        with self.assertRaisesRegex(drills.DrillError, "transport"):
            runner.start()
        state = runner.load()
        self.assertEqual(state["status"], "mutation_unknown")
        self.assertEqual(state["watchdogUnit"], runner._unit())

    def test_stalled_start_lock_cannot_permanently_block_watchdog(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        held = runner._lock()
        try:
            with self.assertRaisesRegex(drills.DrillError, "retry safely"):
                runner.restore(watchdog=True)
        finally:
            held.close()
        runner.restore(watchdog=True)
        self.assertEqual(runner.load()["status"], "restored")

    def test_transient_api_failure_is_safe_to_retry(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.get_failures = 1
        with self.assertRaisesRegex(drills.DrillError, "transient"):
            runner.restore(watchdog=True)
        runner.restore(watchdog=True)
        self.assertEqual(runner.load()["status"], "restored")

    def test_restore_uses_fresh_resource_version_and_container_identity(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.restore()
        tests = [op for op in runner.patches[0] if op["op"] == "test"]
        self.assertIn({"op": "test", "path": "/metadata/resourceVersion", "value": "10"}, tests)
        self.assertIn({"op": "test", "path": "/spec/template/spec/containers/0/name",
                       "value": "catalogue"}, tests)

    def test_uid_drift_refuses_restore(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.obj["metadata"]["uid"] = "replacement"
        with self.assertRaisesRegex(drills.DrillError, "UID drift"):
            runner.restore()
        self.assertEqual(runner.patches, [])

    def test_container_identity_drift_refuses_restore(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.obj["spec"]["template"]["spec"]["containers"][0]["name"] = "renamed"
        with self.assertRaisesRegex(drills.DrillError, "exactly one catalogue"):
            runner.restore()
        self.assertEqual(runner.patches, [])

    def test_service_first_port_identity_and_restore(self):
        runner = FakeRunner(self.temp.name, service())
        state = self.make_state(runner, "catalogue-service-blackhole")
        self.inject_object(runner, state)
        runner.restore()
        tests = [op for op in runner.patches[0] if op["op"] == "test"]
        self.assertIn({"op": "test", "path": "/spec/ports/0/name", "value": "http"}, tests)
        self.assertEqual(runner.obj["spec"]["ports"][0]["targetPort"], 8080)

    def test_service_identity_drift_refuses_restore(self):
        runner = FakeRunner(self.temp.name, service())
        state = self.make_state(runner, "catalogue-service-blackhole")
        self.inject_object(runner, state)
        runner.obj["spec"]["ports"][0]["port"] = 8081
        with self.assertRaisesRegex(drills.DrillError, "identity drift"):
            runner.restore()

    def test_third_party_owned_field_change_is_not_clobbered(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.obj["spec"]["template"]["spec"]["containers"][0]["command"] = ["third-party"]
        with self.assertRaisesRegex(drills.DrillError, "third-party"):
            runner.restore()
        self.assertEqual(runner.patches, [])

    def test_unrelated_change_is_preserved_by_fresh_cas(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.obj["metadata"]["annotations"] = {"third.party/change": "keep"}
        runner.obj["metadata"]["resourceVersion"] = "15"
        runner.restore()
        self.assertEqual(runner.obj["metadata"]["annotations"], {"third.party/change": "keep"})
        rv_test = [op for op in runner.patches[0] if op.get("path") == "/metadata/resourceVersion"]
        self.assertEqual(rv_test[0]["value"], "15")

    def test_absent_fields_are_removed_together_on_restore(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.restore()
        removes = [op["path"] for op in runner.patches[0] if op["op"] == "remove"]
        self.assertEqual([p.rsplit("/", 1)[1] for p in removes], ["command", "readinessProbe"])
        container = runner.obj["spec"]["template"]["spec"]["containers"][0]
        self.assertNotIn("command", container)
        self.assertNotIn("readinessProbe", container)

    def test_manual_cancel_only_after_confirmed_baseline(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        runner.patch_fail = True
        with self.assertRaises(drills.DrillError):
            runner.restore()
        self.assertFalse(runner.cancelled)

    def test_baseline_without_mutation_is_safe_abandoned_cleanup(self):
        runner = FakeRunner(self.temp.name, deployment())
        self.make_state(runner, "catalogue-crashloop")
        runner.restore()
        self.assertEqual(runner.patches, [])
        self.assertTrue(runner.cancelled)
        self.assertEqual(runner.load()["status"], "restored")

    def test_terminal_restored_run_never_reapplies_a_previous_snapshot(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        state = runner.load()
        state["status"] = "restored"
        runner.save(state)
        with self.assertRaisesRegex(drills.DrillError, "terminal restored"):
            runner.restore()
        self.assertEqual(runner.patches, [])

    def test_prepared_run_never_patches_an_unexpected_injected_object(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        state = runner.load()
        state["status"] = "prepared"
        state.pop("watchdogUnit", None)
        runner.save(state)
        with self.assertRaisesRegex(drills.DrillError, "prepared run"):
            runner.restore()
        self.assertEqual(runner.patches, [])

    def test_arming_run_never_patches_an_unexpected_injected_object(self):
        runner = FakeRunner(self.temp.name, deployment())
        state = self.make_state(runner, "catalogue-crashloop")
        self.inject_object(runner, state)
        state = runner.load()
        state["status"] = "arming"
        runner.save(state)
        with self.assertRaisesRegex(drills.DrillError, "arming run"):
            runner.restore()
        self.assertEqual(runner.patches, [])

    def test_fixed_maximums_and_exclusive_active_run(self):
        self.assertEqual({k: v["seconds"] for k, v in drills.DRILLS.items()},
                         {"cart-scale-zero": 360, "catalogue-crashloop": 240,
                          "catalogue-service-blackhole": 300,
                          "fluent-bit-unschedulable": 480,
                          "otel-collector-scale-zero": 240})
        first = FakeRunner(self.temp.name, deployment(), "first-run")
        self.make_state(first, "catalogue-crashloop")
        second = FakeRunner(self.temp.name, deployment(), "second-run")
        with self.assertRaisesRegex(drills.DrillError, "another drill"):
            second._no_other_active()

    def test_watchdog_systemd_restart_and_exact_cli_argv(self):
        runner = drills.Runner("safe-run")
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(drills.subprocess, "run", return_value=completed) as run:
            runner._arm_watchdog(240)
        command = run.call_args_list[0].args[0]
        self.assertIn("--property=Restart=on-failure", command)
        self.assertIn("--property=RestartSec=10s", command)
        self.assertIn("--property=StartLimitIntervalSec=0", command)
        writable = next(arg for arg in command if arg.startswith("--property=ReadWritePaths="))
        self.assertIn(str(runner.dir), writable)
        self.assertIn(str(runner.base / ".active.lock"), writable)
        self.assertEqual(command[-3:], ["watchdog", "--runid", "safe-run"])
        self.assertNotIn("--namespace", command)

    def test_internal_watchdog_parser_invokes_only_watchdog_restore(self):
        instance = mock.Mock()
        with mock.patch.object(drills, "Runner", return_value=instance) as factory:
            self.assertEqual(drills.main(["watchdog", "--runid", "safe-run"]), 0)
        factory.assert_called_once_with("safe-run")
        instance.restore.assert_called_once_with(watchdog=True)

    def test_partial_arm_cleanup_and_inactive_verification(self):
        runner = drills.Runner("safe-run")
        stopped = subprocess.CompletedProcess([], 0, "", "")
        inactive = subprocess.CompletedProcess(
            [], 0, "LoadState=loaded\nActiveState=inactive\nSubState=dead\nJob=\n", "")
        state = {"status": "arming", "watchdogUnit": runner._unit()}
        with mock.patch.object(drills.subprocess, "run", side_effect=[stopped, inactive, inactive]) as run:
            runner._cancel_watchdog(state)
        self.assertEqual(run.call_args_list[0].args[0][1], "stop")
        self.assertEqual(run.call_args_list[1].args[0][1:4], ["show", runner._unit() + ".timer", "-p"])
        self.assertEqual(run.call_args_list[2].args[0][1:4], ["show", runner._unit() + ".service", "-p"])

    def test_cancel_accepts_nonzero_stop_only_when_both_units_prove_inactive(self):
        runner = drills.Runner("safe-run")
        state = {"status": "arming", "watchdogUnit": runner._unit()}
        failed_stop = subprocess.CompletedProcess([], 1, "", "failed")
        absent = subprocess.CompletedProcess(
            [], 0, "LoadState=not-found\nActiveState=inactive\nSubState=dead\nJob=\n", "")
        with mock.patch.object(drills.subprocess, "run",
                               side_effect=[failed_stop, absent, absent]):
            runner._cancel_watchdog(state)

        active = subprocess.CompletedProcess(
            [], 0, "LoadState=loaded\nActiveState=activating\nSubState=auto-restart\nJob=\n", "")
        with mock.patch.object(drills.subprocess, "run",
                               side_effect=[failed_stop, absent, active]):
            with self.assertRaisesRegex(drills.DrillError, "no queued job"):
                runner._cancel_watchdog(state)

        queued = subprocess.CompletedProcess(
            [], 0, "LoadState=loaded\nActiveState=inactive\nSubState=dead\nJob=99 start\n", "")
        with mock.patch.object(drills.subprocess, "run",
                               side_effect=[failed_stop, queued, absent]):
            with self.assertRaisesRegex(drills.DrillError, "no queued job"):
                runner._cancel_watchdog(state)

        unreadable = subprocess.CompletedProcess([], 1, "", "not found")
        with mock.patch.object(drills.subprocess, "run",
                               side_effect=[failed_stop, unreadable]):
            with self.assertRaisesRegex(drills.DrillError, "no queued job"):
                runner._cancel_watchdog(state)

    def test_malformed_sibling_state_fails_closed(self):
        first = FakeRunner(self.temp.name, deployment(), "first-run")
        state = self.make_state(first, "catalogue-crashloop")
        state["status"] = "invented-status"
        (first.dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (first.dir / "state.json").chmod(0o600)
        second = FakeRunner(self.temp.name, deployment(), "second-run")
        with self.assertRaisesRegex(drills.DrillError, "invalid protected state status"):
            second._no_other_active()

    def test_kubectl_has_api_and_process_timeouts(self):
        runner = drills.Runner("safe-run")
        with mock.patch.object(drills.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("kubectl", 15)) as run:
            with self.assertRaisesRegex(drills.DrillError, "outcome may be unknown"):
                runner.kubectl(["get", "pod", "x"], namespace="robot-shop")
        command = run.call_args.args[0]
        self.assertIn("--request-timeout=10s", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_insecure_and_symlink_paths_are_rejected(self):
        root = Path(self.temp.name)
        insecure = root / "insecure"
        insecure.mkdir(mode=0o755)
        with self.assertRaisesRegex(drills.DrillError, "mode"):
            drills.Runner("safe-run", insecure, owner_uid=os.geteuid())._basefd()
        real = root / "real"
        real.mkdir(mode=0o700)
        link = root / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(drills.DrillError, "unsafe"):
            drills.Runner("safe-run", link, owner_uid=os.geteuid())._basefd()
        (real / "target").mkdir(mode=0o700)
        (real / "safe-run").symlink_to(real / "target", target_is_directory=True)
        with self.assertRaisesRegex(drills.DrillError, "unsafe"):
            drills.Runner("safe-run", real, owner_uid=os.geteuid())._runfd()

    @unittest.skipUnless(os.environ.get("RUN_SYSTEMD_INTEGRATION") == "1",
                         "set RUN_SYSTEMD_INTEGRATION=1 as root on an EC2 systemd host")
    def test_actual_early_manual_cancel_before_service_is_loaded(self):
        """Reproduces systemctl stop rc=5 when only the timer exists."""
        self.assertEqual(os.geteuid(), 0, "systemd integration test must run as root")
        runid = "cancel-" + uuid.uuid4().hex[:12]
        runner = drills.Runner(runid)
        unit = runner._unit()
        command = [
            drills.SYSTEMD_RUN, "--quiet", "--unit=" + unit, "--on-active=30s",
            "--timer-property=AccuracySec=1s", "/usr/bin/true",
        ]
        try:
            subprocess.run(command, check=True, timeout=10)
            subprocess.run([drills.SYSTEMCTL, "is-active", "--quiet", unit + ".timer"],
                           check=True, timeout=10)
            runner._cancel_watchdog({"status": "watchdog_armed", "watchdogUnit": unit})
            for suffix in (".timer", ".service"):
                result = subprocess.run(
                    [drills.SYSTEMCTL, "show", unit + suffix, "-p", "LoadState",
                     "-p", "ActiveState", "-p", "SubState", "-p", "Job"],
                    check=True, text=True, stdout=subprocess.PIPE, timeout=10)
                properties = dict(line.split("=", 1) for line in result.stdout.splitlines())
                self.assertIn(properties["LoadState"], {"loaded", "not-found"})
                self.assertEqual(properties["ActiveState"], "inactive")
                self.assertEqual(properties["SubState"], "dead")
                self.assertEqual(properties["Job"], "")
        finally:
            subprocess.run([drills.SYSTEMCTL, "stop", unit + ".timer", unit + ".service"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([drills.SYSTEMCTL, "reset-failed", unit + ".service"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @unittest.skipUnless(os.environ.get("RUN_SYSTEMD_INTEGRATION") == "1",
                         "set RUN_SYSTEMD_INTEGRATION=1 as root on an EC2 systemd host")
    def test_actual_timer_executes_service_and_retries_failure(self):
        self.assertEqual(os.geteuid(), 0, "systemd integration test must run as root")
        test_dir = Path(tempfile.mkdtemp(prefix="drill-systemd-test.", dir="/var/tmp"))
        run_dir = test_dir / "safe-run"
        run_dir.mkdir(mode=0o700)
        lock_path = test_dir / ".active.lock"
        lock_path.write_text("", encoding="utf-8")
        lock_path.chmod(0o600)
        marker = run_dir / "attempts"
        unit = "ts-capstone-drill-test-" + uuid.uuid4().hex[:12]
        command = [
            drills.SYSTEMD_RUN, "--quiet", "--unit=" + unit, "--on-active=1s",
            "--timer-property=AccuracySec=100ms", "--property=Type=oneshot",
            "--property=Restart=on-failure", "--property=RestartSec=1s",
            "--property=StartLimitIntervalSec=0", "--property=ProtectSystem=strict",
            "--property=ReadWritePaths=" + str(run_dir) + " " + str(lock_path),
            drills.PYTHON, str(Path(__file__).resolve()), "--systemd-helper",
            str(marker), str(lock_path),
        ]
        try:
            subprocess.run(command, check=True, timeout=10)
            subprocess.run([drills.SYSTEMCTL, "is-active", "--quiet", unit + ".timer"],
                           check=True, timeout=10)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if marker.exists() and marker.read_text(encoding="utf-8") == "2\n":
                    break
                time.sleep(0.25)
            self.assertEqual(marker.read_text(encoding="utf-8"), "2\n")
            # The helper's first invocation exits 1 and writes 1; only a
            # service restart can produce the observed second invocation and 2.
            result = subprocess.run(
                [drills.SYSTEMCTL, "show", unit + ".service", "-p", "Result", "--value"],
                check=True, text=True, stdout=subprocess.PIPE, timeout=10)
            self.assertEqual(result.stdout.strip(), "success")
        finally:
            subprocess.run([drills.SYSTEMCTL, "stop", unit + ".timer", unit + ".service"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([drills.SYSTEMCTL, "reset-failed", unit + ".service"],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.rmtree(test_dir, ignore_errors=True)


def systemd_helper(marker: Path, lock_path: Path) -> int:
    """Fail once, then succeed; used only by the opt-in EC2 systemd test."""
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    os.close(lock_fd)
    try:
        attempts = int(marker.read_text(encoding="utf-8"))
    except FileNotFoundError:
        attempts = 0
    attempts += 1
    marker.write_text(str(attempts) + "\n", encoding="utf-8")
    return 0 if attempts >= 2 else 1


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--systemd-helper":
        raise SystemExit(systemd_helper(Path(sys.argv[2]), Path(sys.argv[3])))
    unittest.main(verbosity=2)

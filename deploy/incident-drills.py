#!/usr/bin/env python3
"""Fail-safe, allowlisted Robot Shop drills; see the reviewed operator guide."""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BASE = Path("/var/lib/ts-capstone-incident-drills")
KUBECTL = ("/usr/local/bin/k3s", "kubectl")
SYSTEMD_RUN = "/usr/bin/systemd-run"
SYSTEMCTL = "/usr/bin/systemctl"
PYTHON = "/usr/bin/python3"
COMMAND_TIMEOUT = 15
SYSTEMD_TIMEOUT = 10
RUN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,47}$")
ACTIVE = {"prepared", "arming", "watchdog_armed", "mutation_unknown", "injected"}

# The CLI accepts only a drill name. Targets, paths, values and limits are fixed.
DRILLS: dict[str, dict[str, Any]] = {
    "cart-scale-zero": {"namespace": "robot-shop", "kind": "deployment", "name": "cart",
                        "shape": "replicas", "injected": 0, "seconds": 360},
    "catalogue-crashloop": {
        "namespace": "robot-shop", "kind": "deployment", "name": "catalogue",
        "shape": "catalogue", "command": ["/bin/sh", "-c", "exit 42"],
        # Match the API's stored representation: Kubernetes omits the zero-valued
        # initialDelaySeconds default when serializing this probe.
        "probe": {"tcpSocket": {"port": 8080},
                  "timeoutSeconds": 1, "periodSeconds": 2,
                  "successThreshold": 1, "failureThreshold": 1},
        "seconds": 240,
    },
    "catalogue-service-blackhole": {
        "namespace": "robot-shop", "kind": "service", "name": "catalogue",
        "shape": "service", "injected": 65000, "seconds": 300,
    },
    "fluent-bit-unschedulable": {
        "namespace": "log-collection", "kind": "daemonset", "name": "fluent-bit",
        "shape": "nodeSelector",
        "injected": {"incident-drill.invalid/unschedulable": "true"}, "seconds": 480,
    },
    "otel-collector-scale-zero": {
        "namespace": "observability", "kind": "deployment", "name": "otel-collector",
        "shape": "replicas", "injected": 0, "seconds": 240,
    },
}


class DrillError(RuntimeError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def field(name: str, path: str, present: bool, value: Any) -> dict[str, Any]:
    return {"name": name, "path": path, "present": present, "value": copy.deepcopy(value)}


class Runner:
    def __init__(self, runid: str, base: Path = BASE, *, owner_uid: int = 0):
        if not RUN_RE.fullmatch(runid):
            raise DrillError("invalid run id (use 3-48 lowercase letters, digits, or hyphens)")
        self.runid, self.base, self.owner_uid = runid, Path(base), owner_uid
        self.dir = self.base / runid
        self.runner_path = self.dir / "runner.py"

    def _root(self) -> None:
        if os.geteuid() != 0:
            raise DrillError("must run as root on the cluster host")

    def _check(self, st: os.stat_result, kind: str, mode: int, label: str) -> None:
        wanted = stat.S_IFDIR if kind == "dir" else stat.S_IFREG
        if stat.S_IFMT(st.st_mode) != wanted:
            raise DrillError(f"unsafe {label}: wrong file type")
        if st.st_uid != self.owner_uid:
            raise DrillError(f"unsafe {label}: owner must be uid {self.owner_uid}")
        if stat.S_IMODE(st.st_mode) != mode:
            raise DrillError(f"unsafe {label}: mode must be {mode:04o}")

    def _basefd(self, create: bool = False) -> int:
        if create:
            try:
                os.mkdir(self.base, 0o700)
            except FileExistsError:
                pass
        try:
            before = os.lstat(self.base)
            fd = os.open(self.base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise DrillError("protected base is missing or unsafe") from exc
        try:
            after = os.fstat(fd)
            self._check(before, "dir", 0o700, "base")
            self._check(after, "dir", 0o700, "base")
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise DrillError("protected base changed while opening")
            return fd
        except Exception:
            os.close(fd)
            raise

    def _runfd(self, create: bool = False) -> int:
        basefd = self._basefd(create)
        try:
            if create:
                try:
                    os.mkdir(self.runid, 0o700, dir_fd=basefd)
                except FileExistsError:
                    pass
            try:
                before = os.stat(self.runid, dir_fd=basefd, follow_symlinks=False)
                fd = os.open(self.runid, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=basefd)
            except OSError as exc:
                raise DrillError("protected run directory is missing or unsafe") from exc
            try:
                after = os.fstat(fd)
                self._check(before, "dir", 0o700, "run directory")
                self._check(after, "dir", 0o700, "run directory")
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise DrillError("protected run directory changed while opening")
                return fd
            except Exception:
                os.close(fd)
                raise
        finally:
            os.close(basefd)

    def _filefd(self, dirfd: int, name: str, flags: int, mode: int) -> int:
        try:
            fd = os.open(name, flags | os.O_NOFOLLOW, mode, dir_fd=dirfd)
        except OSError as exc:
            raise DrillError(f"protected file {name} is missing or unsafe") from exc
        try:
            self._check(os.fstat(fd), "file", mode, name)
            return fd
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _exists(dirfd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=dirfd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    def _freeze_runner(self, dirfd: int) -> str:
        try:
            source = os.open(Path(__file__), os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise DrillError("runner source must be a regular non-symlink file") from exc
        try:
            if not stat.S_ISREG(os.fstat(source).st_mode):
                raise DrillError("runner source must be a regular file")
            data = bytearray()
            while chunk := os.read(source, 1024 * 1024):
                data.extend(chunk)
        finally:
            os.close(source)
        fd = self._filefd(dirfd, "runner.py",
                          os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(dirfd)
        return digest(bytes(data))

    def _verify_runner(self, state: dict[str, Any]) -> None:
        dirfd = self._runfd()
        try:
            fd = self._filefd(dirfd, "runner.py", os.O_RDONLY, 0o500)
            try:
                data = bytearray()
                while chunk := os.read(fd, 1024 * 1024):
                    data.extend(chunk)
            finally:
                os.close(fd)
        finally:
            os.close(dirfd)
        if digest(bytes(data)) != state.get("runnerSha256"):
            raise DrillError("frozen runner hash mismatch")

    def audit(self, event: str, **extra: Any) -> None:
        record = {"time": int(time.time()), "event": event, "runid": self.runid, **extra}
        dirfd = self._runfd()
        try:
            flags = os.O_WRONLY | os.O_APPEND
            if not self._exists(dirfd, "audit.jsonl"):
                flags |= os.O_CREAT | os.O_EXCL
            fd = self._filefd(dirfd, "audit.jsonl", flags, 0o600)
            try:
                os.write(fd, (canonical(record) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            os.close(dirfd)

    def save(self, state: dict[str, Any]) -> None:
        self._validate_state(state)
        dirfd = self._runfd()
        temp = f".state-{os.getpid()}-{time.monotonic_ns()}"
        try:
            fd = self._filefd(dirfd, temp,
                              os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                data = (canonical(state) + "\n").encode()
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temp, "state.json", src_dir_fd=dirfd, dst_dir_fd=dirfd)
            os.fsync(dirfd)
        finally:
            try:
                os.unlink(temp, dir_fd=dirfd)
            except FileNotFoundError:
                pass
            os.close(dirfd)

    def load(self) -> dict[str, Any]:
        dirfd = self._runfd()
        try:
            fd = self._filefd(dirfd, "state.json", os.O_RDONLY, 0o600)
            try:
                data = os.read(fd, 128 * 1024 + 1)
            finally:
                os.close(fd)
        finally:
            os.close(dirfd)
        if len(data) > 128 * 1024:
            raise DrillError("protected state is unexpectedly large")
        try:
            state = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DrillError("missing or invalid protected state") from exc
        self._validate_state(state)
        self._verify_runner(state)
        return state

    def _allowed_fields(self, drill: str, identity: Any) -> list[dict[str, Any]]:
        spec = DRILLS[drill]
        if spec["shape"] == "replicas":
            return [{"name": "replicas", "path": "/spec/replicas", "injected": spec["injected"]}]
        if spec["shape"] == "nodeSelector":
            return [{"name": "nodeSelector", "path": "/spec/template/spec/nodeSelector",
                     "injected": spec["injected"]}]
        if spec["shape"] == "service":
            if not isinstance(identity, dict) or identity.get("portIndex") != 0:
                raise DrillError("invalid service port identity")
            return [{"name": "targetPort", "path": "/spec/ports/0/targetPort",
                     "injected": spec["injected"]}]
        if (not isinstance(identity, dict) or identity.get("containerName") != "catalogue"
                or not isinstance(identity.get("containerIndex"), int)
                or not 0 <= identity["containerIndex"] <= 63):
            raise DrillError("invalid container identity")
        prefix = f"/spec/template/spec/containers/{identity['containerIndex']}"
        return [
            {"name": "command", "path": prefix + "/command", "injected": spec["command"]},
            {"name": "readinessProbe", "path": prefix + "/readinessProbe",
             "injected": spec["probe"]},
        ]

    def _validate_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state, dict) or state.get("version") != 2 or state.get("runid") != self.runid:
            raise DrillError("invalid protected state identity")
        if state.get("status") not in ACTIVE | {"restored"}:
            raise DrillError("invalid protected state status")
        if not re.fullmatch(r"[0-9a-f]{64}", str(state.get("runnerSha256", ""))):
            raise DrillError("invalid frozen runner hash in state")
        snap = state.get("snapshot")
        if not isinstance(snap, dict) or snap.get("drill") not in DRILLS:
            raise DrillError("invalid protected snapshot")
        spec = DRILLS[snap["drill"]]
        for key in ("namespace", "kind", "name", "seconds"):
            if snap.get(key) != spec[key]:
                raise DrillError("protected snapshot is outside the allowlist")
        if not isinstance(snap.get("uid"), str) or not snap["uid"]:
            raise DrillError("invalid snapshot UID")
        if not isinstance(snap.get("resourceVersion"), str) or not snap["resourceVersion"]:
            raise DrillError("invalid snapshot resourceVersion")
        allowed = self._allowed_fields(snap["drill"], snap.get("identity"))
        actual = snap.get("fields")
        if not isinstance(actual, list) or len(actual) != len(allowed):
            raise DrillError("protected snapshot fields are outside the allowlist")
        for saved, expected in zip(actual, allowed):
            if (not isinstance(saved, dict) or saved.get("name") != expected["name"]
                    or saved.get("path") != expected["path"]
                    or saved.get("injected") != expected["injected"]
                    or not isinstance(saved.get("present"), bool)):
                raise DrillError("protected snapshot mutation is outside the allowlist")

    def kubectl(self, args: list[str], *, namespace: str) -> str:
        cmd = [*KUBECTL, "--request-timeout=10s", "-n", namespace, *args]
        try:
            result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, check=True,
                                    timeout=COMMAND_TIMEOUT)
            return result.stdout
        except subprocess.TimeoutExpired as exc:
            raise DrillError("kubectl timed out; mutation outcome may be unknown") from exc
        except subprocess.CalledProcessError as exc:
            raise DrillError("kubectl failed: " + exc.stderr.strip()) from exc

    def get(self, drill: str) -> dict[str, Any]:
        spec = DRILLS[drill]
        return json.loads(self.kubectl(["get", spec["kind"], spec["name"], "-o", "json"],
                                       namespace=spec["namespace"]))

    def _inspect(self, obj: dict[str, Any], drill: str) -> dict[str, Any]:
        spec, metadata = DRILLS[drill], obj.get("metadata", {})
        uid, rv = metadata.get("uid"), metadata.get("resourceVersion")
        if not isinstance(uid, str) or not uid or not isinstance(rv, str) or not rv:
            raise DrillError("target missing UID/resourceVersion")
        generation = field("generation", "/metadata/generation", "generation" in metadata,
                           metadata.get("generation"))
        shape = spec["shape"]
        if shape == "replicas":
            values = obj.get("spec", {})
            fields = [field("replicas", "/spec/replicas", "replicas" in values,
                            values.get("replicas"))]
            identity: dict[str, Any] = {}
        elif shape == "nodeSelector":
            values = obj.get("spec", {}).get("template", {}).get("spec", {})
            fields = [field("nodeSelector", "/spec/template/spec/nodeSelector",
                            "nodeSelector" in values, values.get("nodeSelector"))]
            identity = {}
        elif shape == "service":
            ports = obj.get("spec", {}).get("ports", [])
            if not isinstance(ports, list) or not ports or not isinstance(ports[0], dict):
                raise DrillError("catalogue Service first port is missing")
            port = ports[0]
            protocol = field("protocol", "/spec/ports/0/protocol", "protocol" in port,
                             port.get("protocol"))
            identity = {"portIndex": 0, "name": port.get("name"), "port": port.get("port"),
                        "protocol": protocol}
            fields = [field("targetPort", "/spec/ports/0/targetPort",
                            "targetPort" in port, port.get("targetPort"))]
        else:
            containers = obj.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            matches = [(i, c) for i, c in enumerate(containers)
                       if isinstance(c, dict) and c.get("name") == "catalogue"]
            if len(matches) != 1:
                raise DrillError("expected exactly one catalogue container")
            index, container = matches[0]
            prefix = f"/spec/template/spec/containers/{index}"
            identity = {"containerIndex": index, "containerName": "catalogue"}
            fields = [
                field("command", prefix + "/command", "command" in container,
                      container.get("command")),
                field("readinessProbe", prefix + "/readinessProbe",
                      "readinessProbe" in container, container.get("readinessProbe")),
            ]
        return {"uid": uid, "resourceVersion": rv, "generation": generation,
                "identity": identity, "fields": fields}

    def _approved_baseline(self, drill: str, current: dict[str, Any]) -> None:
        spec, fields = DRILLS[drill], current["fields"]
        if spec["shape"] == "replicas":
            if not fields[0]["present"] or fields[0]["value"] != 1:
                raise DrillError("approved baseline requires explicit replicas=1")
        elif spec["shape"] == "nodeSelector":
            if fields[0]["present"]:
                raise DrillError("approved Fluent Bit baseline requires nodeSelector absent")
        elif spec["shape"] == "service":
            ident, protocol = current["identity"], current["identity"]["protocol"]
            if ident["name"] != "http" or ident["port"] != 8080:
                raise DrillError("approved Service baseline requires first port http:8080")
            if protocol["present"] and protocol["value"] != "TCP":
                raise DrillError("approved Service protocol must be TCP or omitted")
            if not fields[0]["present"] or fields[0]["value"] != 8080:
                raise DrillError("approved Service targetPort must be 8080")
        elif any(item["present"] for item in fields):
            raise DrillError("approved catalogue command and readinessProbe must both be absent")

    def snapshot(self, drill: str) -> dict[str, Any]:
        current = self._inspect(self.get(drill), drill)
        self._approved_baseline(drill, current)
        spec, fields = DRILLS[drill], []
        for observed, allowed in zip(current["fields"],
                                     self._allowed_fields(drill, current["identity"])):
            fields.append({**observed, "injected": copy.deepcopy(allowed["injected"])})
        return {"drill": drill, "namespace": spec["namespace"], "kind": spec["kind"],
                "name": spec["name"], "seconds": spec["seconds"], "uid": current["uid"],
                "resourceVersion": current["resourceVersion"],
                "generation": current["generation"], "identity": current["identity"],
                "fields": fields}

    def _lock(self):
        basefd = self._basefd(create=True)
        try:
            if self._exists(basefd, ".active.lock"):
                fd = self._filefd(basefd, ".active.lock", os.O_RDWR, 0o600)
            else:
                fd = self._filefd(basefd, ".active.lock",
                                  os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                # Never wait behind a wedged start. A watchdog attempt fails fast;
                # Restart=on-failure gives it a new bounded attempt ten seconds later.
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                os.close(fd)
                raise DrillError("another drill operation is active; retry safely") from exc
            return os.fdopen(fd, "r+")
        finally:
            os.close(basefd)

    def _sibling_state(self, basefd: int, name: str) -> dict[str, Any]:
        try:
            st = os.stat(name, dir_fd=basefd, follow_symlinks=False)
            self._check(st, "dir", 0o700, f"run {name}")
            dirfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=basefd)
        except OSError as exc:
            raise DrillError(f"unsafe sibling run directory {name}") from exc
        try:
            fd = self._filefd(dirfd, "state.json", os.O_RDONLY, 0o600)
            try:
                data = os.read(fd, 128 * 1024 + 1)
            finally:
                os.close(fd)
        finally:
            os.close(dirfd)
        try:
            state = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DrillError(f"invalid sibling state for {name}") from exc
        # Fail closed on unknown statuses, tampered targets/paths, or a replaced
        # sibling runner. A corrupt active record must never permit a new drill.
        sibling = Runner(name, self.base, owner_uid=self.owner_uid)
        sibling._validate_state(state)
        sibling._verify_runner(state)
        return state

    def _no_other_active(self) -> None:
        basefd = self._basefd()
        try:
            for name in os.listdir(basefd):
                if name.startswith(".") or name == self.runid:
                    continue
                if not RUN_RE.fullmatch(name):
                    raise DrillError("unexpected protected-base entry; refusing operation")
                if self._sibling_state(basefd, name).get("status") in ACTIVE:
                    raise DrillError("another drill is not recovered; no next drill")
        finally:
            os.close(basefd)

    def _systemd(self, cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, check=check,
                                  timeout=SYSTEMD_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            raise DrillError("systemd command timed out") from exc
        except subprocess.CalledProcessError as exc:
            raise DrillError("systemd command failed: " + exc.stderr.strip()) from exc

    def _unit(self) -> str:
        return "ts-capstone-drill-" + self.runid

    def _arm_watchdog(self, seconds: int) -> str:
        unit = self._unit()
        cmd = [
            SYSTEMD_RUN, "--quiet", "--unit=" + unit, "--on-active=" + str(seconds) + "s",
            "--timer-property=AccuracySec=1s", "--property=Type=oneshot",
            "--property=Restart=on-failure", "--property=RestartSec=10s",
            "--property=StartLimitIntervalSec=0", "--property=NoNewPrivileges=yes",
            "--property=ProtectSystem=strict", "--property=ProtectHome=yes",
            "--property=PrivateTmp=yes",
            # The watchdog writes state/audit in the run directory and opens the
            # already-created global lock O_RDWR. Keep every other path read-only.
            "--property=ReadWritePaths=" + str(self.dir) + " " + str(self.base / ".active.lock"),
            PYTHON, str(self.runner_path), "watchdog", "--runid", self.runid,
        ]
        try:
            self._systemd(cmd)
            self._systemd([SYSTEMCTL, "is-active", "--quiet", unit + ".timer"])
        except DrillError:
            try:
                self._systemd([SYSTEMCTL, "stop", unit + ".timer", unit + ".service"],
                              check=False)
            except DrillError:
                pass
            raise DrillError("watchdog arm/verification failed; no mutation")
        return unit

    def _cancel_watchdog(self, state: dict[str, Any]) -> None:
        """Only call after a fresh API read proves the complete baseline."""
        unit = state.get("watchdogUnit")
        if unit is None and state.get("status") != "arming":
            return
        if unit is None:
            unit = self._unit()
        if unit != self._unit():
            raise DrillError("invalid watchdog unit in protected state")
        stopped = self._systemd([SYSTEMCTL, "stop", unit + ".timer", unit + ".service"],
                                check=False)
        # systemctl returns a non-zero status when a transient service has not
        # been loaded yet, even if it successfully stopped the timer.  Judge
        # cancellation by both units' explicit post-stop states.  This remains
        # fail-closed for an active/activating unit, a queued job, an unexpected
        # load/sub-state, or an unreadable status.
        for suffix in (".timer", ".service"):
            observed = self._systemd([SYSTEMCTL, "show", unit + suffix,
                                      "-p", "LoadState", "-p", "ActiveState",
                                      "-p", "SubState", "-p", "Job"], check=False)
            properties = {}
            for line in observed.stdout.splitlines():
                key, separator, value = line.partition("=")
                if separator and key not in properties:
                    properties[key] = value
            if (observed.returncode != 0
                    or properties.get("LoadState") not in {"loaded", "not-found"}
                    or properties.get("ActiveState") != "inactive"
                    or properties.get("SubState") != "dead"
                    or properties.get("Job") != ""):
                detail = " after non-zero stop" if stopped.returncode else ""
                raise DrillError("watchdog cancellation could not prove "
                                 + suffix + " inactive with no queued job" + detail)

    def _identity_tests(self, snap: dict[str, Any]) -> list[dict[str, Any]]:
        shape, ident = DRILLS[snap["drill"]]["shape"], snap["identity"]
        if shape == "catalogue":
            return [{"op": "test",
                     "path": f"/spec/template/spec/containers/{ident['containerIndex']}/name",
                     "value": "catalogue"}]
        if shape == "service":
            tests = [{"op": "test", "path": "/spec/ports/0/name", "value": "http"},
                     {"op": "test", "path": "/spec/ports/0/port", "value": 8080}]
            if ident["protocol"]["present"]:
                tests.append({"op": "test", "path": "/spec/ports/0/protocol",
                              "value": ident["protocol"]["value"]})
            return tests
        return []

    def _guards(self, snap: dict[str, Any], resource_version: str) -> list[dict[str, Any]]:
        return [{"op": "test", "path": "/metadata/uid", "value": snap["uid"]},
                {"op": "test", "path": "/metadata/resourceVersion",
                 "value": resource_version}, *self._identity_tests(snap)]

    def _patch(self, drill: str, patch: list[dict[str, Any]]) -> None:
        spec = DRILLS[drill]
        self.kubectl(["patch", spec["kind"], spec["name"], "--type=json",
                      "-p", canonical(patch)], namespace=spec["namespace"])

    def _matches(self, current: dict[str, Any], snap: dict[str, Any], which: str) -> bool:
        if current["uid"] != snap["uid"] or current["identity"] != snap["identity"]:
            return False
        for now, saved in zip(current["fields"], snap["fields"]):
            if now["name"] != saved["name"] or now["path"] != saved["path"]:
                return False
            if which == "baseline":
                if now["present"] != saved["present"] or now["value"] != saved["value"]:
                    return False
            elif not now["present"] or now["value"] != saved["injected"]:
                return False
        return True

    def prepare(self, drill: str) -> None:
        self._root()
        lock = self._lock()
        try:
            self._no_other_active()
            basefd = self._basefd()
            try:
                if self._exists(basefd, self.runid):
                    raise DrillError("run id already exists")
            finally:
                os.close(basefd)
            snap = self.snapshot(drill)
            dirfd = self._runfd(create=True)
            try:
                runner_hash = self._freeze_runner(dirfd)
            finally:
                os.close(dirfd)
            state = {"version": 2, "runid": self.runid, "status": "prepared",
                     "runnerSha256": runner_hash, "snapshot": snap}
            self.save(state)
            self.audit("prepared", drill=drill, uid=snap["uid"],
                       resourceVersion=snap["resourceVersion"], generation=snap["generation"])
            print(canonical({"runid": self.runid, "status": "prepared", "drill": drill,
                             "maxSeconds": snap["seconds"], "runner": str(self.runner_path)}))
        finally:
            lock.close()

    def start(self) -> None:
        self._root()
        lock = self._lock()
        try:
            state = self.load()
            self._no_other_active()
            if state["status"] != "prepared":
                raise DrillError("only a prepared drill can start")
            snap = state["snapshot"]
            current = self._inspect(self.get(snap["drill"]), snap["drill"])
            if (current["resourceVersion"] != snap["resourceVersion"]
                    or not self._matches(current, snap, "baseline")):
                raise DrillError("target drift since prepare; no mutation")
            state["status"] = "arming"
            state["watchdogUnit"] = self._unit()
            self.save(state)
            unit = self._arm_watchdog(snap["seconds"])
            state["watchdogUnit"], state["status"] = unit, "watchdog_armed"
            self.save(state)
            self.audit("watchdog_armed", unit=unit, seconds=snap["seconds"])
            patch = self._guards(snap, current["resourceVersion"])
            for saved in snap["fields"]:
                if saved["present"]:
                    patch.append({"op": "test", "path": saved["path"],
                                  "value": saved["value"]})
                patch.append({"op": "replace" if saved["present"] else "add",
                              "path": saved["path"], "value": saved["injected"]})
            self.audit("injection_attempt", fields=[x["name"] for x in snap["fields"]])
            try:
                self._patch(snap["drill"], patch)
                post = self._inspect(self.get(snap["drill"]), snap["drill"])
                if not self._matches(post, snap, "injected"):
                    raise DrillError("post-injection confirmation mismatch")
            except DrillError:
                state["status"] = "mutation_unknown"
                self.save(state)
                self.audit("injection_unknown")
                raise
            state["status"] = "injected"
            state["startedAt"] = int(time.time())
            state["postInjection"] = {"resourceVersion": post["resourceVersion"],
                                      "generation": post["generation"]}
            self.save(state)
            self.audit("injected", resourceVersion=post["resourceVersion"],
                       generation=post["generation"])
            print(canonical({"runid": self.runid, "status": "injected", "watchdog": unit,
                             "deadlineSeconds": snap["seconds"]}))
        finally:
            lock.close()

    def restore(self, *, watchdog: bool = False) -> None:
        self._root()
        lock = self._lock()
        try:
            state = self.load()
            snap, drill = state["snapshot"], state["snapshot"]["drill"]
            # A fresh GET occurs on every attempt. Unrelated spec edits are
            # preserved: their new RV is used as the CAS guard while only owned
            # fields are changed. Identity or owned-field drift is refused.
            current = self._inspect(self.get(drill), drill)
            if current["uid"] != snap["uid"]:
                raise DrillError("UID drift: refusing restore")
            if current["identity"] != snap["identity"]:
                raise DrillError("resource identity drift: refusing restore")
            # A terminal record is evidence only.  It must never later become
            # an authority to overwrite a new drill or a human change that
            # happens to use this run's injected value.
            if state["status"] == "restored":
                if not self._matches(current, snap, "baseline"):
                    raise DrillError("terminal restored run refuses to modify workload")
                print(canonical({"runid": self.runid, "status": "already_restored"}))
                return
            # `prepared` and `arming` occur before the mutation attempt.  They
            # can only be abandoned after proving the baseline; `arming` may
            # still need its successfully armed watchdog cancelled below.
            if (state["status"] in {"prepared", "arming"}
                    and not self._matches(current, snap, "baseline")):
                raise DrillError(state["status"] + " run refuses to modify workload")
            if self._matches(current, snap, "baseline"):
                if not watchdog:
                    self._cancel_watchdog(state)
                state["status"] = "restored"
                state["restoredGeneration"] = current["generation"]
                self.save(state)
                self.audit("already_restored", watchdog=watchdog,
                           resourceVersion=current["resourceVersion"],
                           generation=current["generation"])
                print(canonical({"runid": self.runid, "status": "already_restored"}))
                return
            if not self._matches(current, snap, "injected"):
                raise DrillError("third-party owned-field change: refusing to clobber")
            patch = self._guards(snap, current["resourceVersion"])
            for now, saved in zip(current["fields"], snap["fields"]):
                patch.append({"op": "test", "path": now["path"],
                              "value": saved["injected"]})
            for saved in snap["fields"]:
                patch.append({"op": "replace" if saved["present"] else "remove",
                              "path": saved["path"], **({"value": saved["value"]}
                              if saved["present"] else {})})
            self.audit("restore_attempt", watchdog=watchdog,
                       resourceVersion=current["resourceVersion"],
                       generation=current["generation"])
            self._patch(drill, patch)
            confirm = self._inspect(self.get(drill), drill)
            if not self._matches(confirm, snap, "baseline"):
                raise DrillError("restore confirmation failed; watchdog remains active")
            if not watchdog:
                self._cancel_watchdog(state)
            state["status"] = "restored"
            state["restoredGeneration"] = confirm["generation"]
            self.save(state)
            self.audit("restored", watchdog=watchdog,
                       resourceVersion=confirm["resourceVersion"],
                       generation=confirm["generation"])
            print(canonical({"runid": self.runid, "status": "restored"}))
        finally:
            lock.close()

    def status(self) -> None:
        self._root()
        state = self.load()
        snap = state["snapshot"]
        print(canonical({"runid": self.runid, "status": state["status"],
                         "drill": snap["drill"], "maxSeconds": snap["seconds"],
                         "watchdog": state.get("watchdogUnit")}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "start", "restore", "status", "watchdog"))
    parser.add_argument("--runid", required=True)
    parser.add_argument("--drill", choices=tuple(DRILLS))
    args = parser.parse_args(argv)
    runner = Runner(args.runid)
    try:
        if args.action == "prepare":
            if not args.drill:
                raise DrillError("--drill is required for prepare")
            runner.prepare(args.drill)
        elif args.drill:
            raise DrillError("--drill is accepted only by prepare")
        elif args.action == "start":
            runner.start()
        elif args.action == "restore":
            runner.restore()
        elif args.action == "watchdog":
            runner.restore(watchdog=True)
        else:
            runner.status()
        return 0
    except DrillError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

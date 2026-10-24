#!/usr/bin/env python3
"""Run the logging NetworkPolicy proof from a privileged cluster operator host."""

import json
import subprocess
import sys
import time
import uuid


KUBECTL = ["sudo", "k3s", "kubectl"]
LOG_NAMESPACE = "log-collection"
ROBOT_NAMESPACE = "robot-shop"
POD_PREFIX = "ts-capstone-network-check"
CONTROL_PREFIX = "ts-capstone-network-control"
PROBE_IMAGE = (
    "robotshop/rs-payment@sha256:"
    "774b52c6180d8f3273f77230d70ace9c45e1f8909e21e10a19ed83b1cec53bb3"
)
MAX_OUTPUT = 4096

# This script intentionally emits only these fixed result keys from the test pod.
PROBE_CODE = r'''
import json
import socket
import sys

targets = {
    "api": ("kubernetes.default.svc", 443),
    "loki": ("loki.observability.svc.cluster.local", 3100),
    "prometheus": ("kube-prometheus-stack-prometheus.observability.svc.cluster.local", 9090),
    "internet": ("example.org", 443),
}

def resolves(host):
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False

def connects(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False

result = {
    "api_dns": resolves(targets["api"][0]),
    "loki_dns": resolves(targets["loki"][0]),
    "api_443": connects(*targets["api"]),
    "loki_3100": connects(*targets["loki"]),
    "prometheus_9090": connects(*targets["prometheus"]),
    "example_443": connects(*targets["internet"]),
}
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
expected = (
    result["api_dns"]
    and result["loki_dns"]
    and result["api_443"]
    and result["loki_3100"]
    and not result["prometheus_9090"]
    and not result["example_443"]
)
sys.exit(0 if expected else 1)
'''

POSITIVE_CONTROL_CODE = r'''
import json
import socket
import sys

try:
    with socket.create_connection(("example.org", 443), timeout=3):
        pass
    print('{"example_443":true}')
except OSError:
    print('{"example_443":false}')
    sys.exit(1)
'''


class ProbeError(Exception):
    pass


def run_kubectl(args, *, input_text=None, timeout=15, check=True):
    """Keep JSON intact; bound displayed diagnostics and use no shell."""
    try:
        completed = subprocess.run(
            KUBECTL + args,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("kubectl timeout") from exc

    stdout = completed.stdout
    stderr = completed.stderr[:MAX_OUTPUT]
    if check and completed.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "kubectl failed"
        raise ProbeError(detail[:MAX_OUTPUT])
    return completed.returncode, stdout, stderr


def get_json(args, *, timeout=15):
    _, stdout, _ = run_kubectl(args + ["-o", "json"], timeout=timeout)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError("kubectl returned invalid JSON") from exc


def control_manifest(name):
    """Create an egress-independent control outside all Robot Shop selectors."""
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": ROBOT_NAMESPACE,
            "labels": {"capstone.tsacademy/flow": "network-positive-control"},
        },
        "spec": {
            "restartPolicy": "Never",
            "activeDeadlineSeconds": 45,
            "automountServiceAccountToken": False,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "network-positive-control",
                    "image": PROBE_IMAGE,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["python", "-c", POSITIVE_CONTROL_CODE],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "runAsNonRoot": True,
                        "capabilities": {"drop": ["ALL"]},
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "32Mi"},
                        "limits": {"cpu": "100m", "memory": "96Mi"},
                    },
                }
            ],
        },
    }


def assert_positive_control():
    """Prove internet reachability without relying on payment egress policy."""
    name = f"{CONTROL_PREFIX}-{uuid.uuid4().hex[:12]}"
    created_uid = None
    try:
        run_kubectl(["create", "-f", "-"], input_text=json.dumps(control_manifest(name)), timeout=20)
        created = get_created_pod(ROBOT_NAMESPACE, name)
        created_uid = created.get("metadata", {}).get("uid")
        if not created_uid:
            raise ProbeError("positive control did not return a UID")
        terminal = wait_for_terminal_pod(ROBOT_NAMESPACE, name, timeout_seconds=45)
        _, stdout, _ = run_kubectl(
            ["-n", ROBOT_NAMESPACE, "logs", name, "--tail=5"], timeout=15, check=False
        )
        lines = [line for line in stdout.splitlines() if line.strip()]
        if terminal.get("status", {}).get("phase") != "Succeeded" or lines != ['{"example_443":true}']:
            raise ProbeError("inconclusive: dedicated positive control could not reach example.org:443")
    finally:
        if created_uid is not None:
            cleanup_created_pod(ROBOT_NAMESPACE, name, created_uid)


def probe_manifest(name):
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": LOG_NAMESPACE,
            "labels": {
                "capstone.tsacademy/flow": "logging",
            },
        },
        "spec": {
            "restartPolicy": "Never",
            "activeDeadlineSeconds": 90,
            "automountServiceAccountToken": False,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "network-check",
                    "image": PROBE_IMAGE,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["python", "-c", PROBE_CODE],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "runAsNonRoot": True,
                        "capabilities": {"drop": ["ALL"]},
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "32Mi"},
                        "limits": {"cpu": "100m", "memory": "96Mi"},
                    },
                }
            ],
        },
    }


def cleanup_created_pod(namespace, name, expected_uid):
    """Delete only the unique probe pod, and only if its UID still matches."""
    try:
        pod = get_json(["-n", namespace, "get", "pod", name], timeout=10)
    except ProbeError:
        return
    if pod.get("metadata", {}).get("uid") != expected_uid:
        return
    run_kubectl(["-n", namespace, "delete", "pod", name], timeout=20, check=False)


def wait_for_terminal_pod(namespace, name, timeout_seconds=90):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        pod = get_json(["-n", namespace, "get", "pod", name], timeout=10)
        phase = pod.get("status", {}).get("phase")
        if phase in {"Succeeded", "Failed"}:
            return pod
        time.sleep(2)
    raise ProbeError("probe pod did not reach a terminal phase within 90 seconds")


def get_created_pod(namespace, name):
    """Wait briefly for the API server to return the object created above."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return get_json(["-n", namespace, "get", "pod", name], timeout=10)
        except ProbeError as exc:
            if "NotFound" not in str(exc):
                raise
            time.sleep(0.5)
    raise ProbeError("created probe did not become readable within 10 seconds")


def read_probe_result(name):
    _, stdout, _ = run_kubectl(
        ["-n", LOG_NAMESPACE, "logs", name, "--tail=20"], timeout=15, check=False
    )
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ProbeError("probe did not return one structured result")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ProbeError("probe returned invalid result JSON") from exc
    expected_keys = {
        "api_dns",
        "loki_dns",
        "api_443",
        "loki_3100",
        "prometheus_9090",
        "example_443",
    }
    if set(result) != expected_keys or not all(isinstance(value, bool) for value in result.values()):
        raise ProbeError("probe result has unexpected fields")
    return result


def main():
    name = f"{POD_PREFIX}-{uuid.uuid4().hex[:12]}"
    created_uid = None
    try:
        # A failed positive control means a denied external connection is not evidence of policy.
        assert_positive_control()
        run_kubectl(
            ["create", "-f", "-"],
            input_text=json.dumps(probe_manifest(name)),
            timeout=20,
        )
        try:
            created = get_created_pod(LOG_NAMESPACE, name)
            created_uid = created["metadata"]["uid"]
        except KeyError as exc:
            raise ProbeError("created probe did not return a UID") from exc

        terminal = wait_for_terminal_pod(LOG_NAMESPACE, name)
        result = read_probe_result(name)
        passed = (
            terminal.get("status", {}).get("phase") == "Succeeded"
            and result["api_dns"]
            and result["loki_dns"]
            and result["api_443"]
            and result["loki_3100"]
            and not result["prometheus_9090"]
            and not result["example_443"]
        )
        if not passed:
            raise ProbeError("network policy expectations were not all met")
        print("PASS")
        return 0
    except ProbeError as exc:
        print(f"FAIL: {str(exc)[:MAX_OUTPUT]}")
        return 1
    finally:
        if created_uid is not None:
            cleanup_created_pod(LOG_NAMESPACE, name, created_uid)


if __name__ == "__main__":
    sys.exit(main())

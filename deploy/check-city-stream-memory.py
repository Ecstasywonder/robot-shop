"""Representative 18 MiB city-feed check using Locust's real HttpSession."""

import importlib.util
import json
import multiprocessing
import resource
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gevent import joinall, spawn
from locust.env import Environment


TARGET_BODY_BYTES = 18_239_043


def load_workload(path):
    spec = importlib.util.spec_from_file_location("workload", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def serve_city_fixture(port_queue, request_count):
    completed = threading.Event()
    counter_lock = threading.Lock()
    completed_requests = [0]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/api/shipping/cities/US":
                self.send_error(404)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"[")
                bytes_written = 1
                next_uuid = 0
                while bytes_written + 1 < TARGET_BODY_BYTES:
                    records = []
                    for offset in range(1000):
                        city_id = next_uuid + offset
                        records.append(
                            json.dumps(
                                {
                                    "city": "São-東京-🌍-{:07d}".format(city_id),
                                    "code": "US",
                                    "latitude": 40.7128,
                                    "longitude": -74.006,
                                    "name": "Representative 城市 🌍 {:07d}".format(city_id),
                                    "region": "Région 東京",
                                    "uuid": city_id,
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        )
                    batch = b",".join(records)
                    if next_uuid:
                        batch = b"," + batch
                    self.wfile.write(batch)
                    bytes_written += len(batch)
                    next_uuid += len(records)
                self.wfile.write(b"]")
            finally:
                with counter_lock:
                    completed_requests[0] += 1
                    if completed_requests[0] == request_count:
                        completed.set()

        def log_message(self, format_string, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.25
    port_queue.put(server.server_port)
    while not completed.is_set():
        server.handle_request()
    server.server_close()


def cgroup_peak_bytes():
    for path in (
        "/sys/fs/cgroup/memory.peak",
        "/sys/fs/cgroup/memory/memory.max_usage_in_bytes",
    ):
        try:
            with open(path) as peak_file:
                return int(peak_file.read().strip())
        except (FileNotFoundError, ValueError):
            continue
    return None


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in (
        "stream",
        "stream-two",
        "materialize",
        "materialize-two",
    ):
        raise SystemExit(
            "usage: check-city-stream-memory.py WORKLOAD "
            "{stream|stream-two|materialize|materialize-two}"
        )
    workload = load_workload(sys.argv[1])
    mode = sys.argv[2]
    user_count = 2 if mode.endswith("-two") else 1
    streaming = mode.startswith("stream")

    port_queue = multiprocessing.Queue()
    server = multiprocessing.Process(
        target=serve_city_fixture, args=(port_queue, user_count)
    )
    server.start()
    port = port_queue.get(timeout=10)

    events = []
    environment = Environment()

    def capture_request(**kwargs):
        events.append(kwargs)

    environment.events.request.add_listener(capture_request)
    workload.UserBehavior.host = "http://127.0.0.1:{}".format(port)
    users = [workload.UserBehavior(environment) for _ in range(user_count)]
    before_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.perf_counter()

    selected = [None] * user_count

    def make_request(index):
        if streaming:
            selected[index] = workload.fetch_random_city(
                users[index].client, "US", "192.0.2.10"
            )
        else:
            response = users[index].client.get(
                "/api/shipping/cities/US", name="/api/shipping/cities/{country_code}"
            )
            selected[index] = response.json()[0]

    workers = [spawn(make_request, index) for index in range(user_count)]
    joinall(workers, raise_error=True)
    elapsed_seconds = time.perf_counter() - started

    after_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    server.join(timeout=10)
    if server.is_alive():
        server.terminate()
        server.join(timeout=5)
        raise AssertionError("fixture server did not exit")
    assert server.exitcode == 0
    event_summary = [
        {
            "exception": str(event.get("exception")),
            "response_length": event.get("response_length"),
            "response_time": event.get("response_time"),
        }
        for event in events
    ]
    assert all(city is not None and city["name"] for city in selected), event_summary
    assert len(events) == user_count, events
    assert all(event.get("exception") is None for event in events), events
    response_lengths = [event["response_length"] for event in events]
    assert all(length >= TARGET_BODY_BYTES for length in response_lengths), response_lengths
    peak_delta_bytes = max(0, after_kib - before_kib) * 1024
    container_peak_bytes = cgroup_peak_bytes()
    if streaming:
        assert peak_delta_bytes < 64 * 1024 * 1024, peak_delta_bytes
        if container_peak_bytes is not None:
            assert container_peak_bytes < 192 * 1024 * 1024, container_peak_bytes
    print(
        "PASS: mode={} users={} body_bytes_each={} peak_rss_bytes={} "
        "peak_rss_delta_bytes={} cgroup_peak_bytes={} elapsed_seconds={:.3f} "
        "response_time_ms={}".format(
            mode,
            user_count,
            response_lengths,
            after_kib * 1024,
            peak_delta_bytes,
            container_peak_bytes,
            elapsed_seconds,
            [round(event["response_time"], 3) for event in events],
        )
    )


if __name__ == "__main__":
    main()

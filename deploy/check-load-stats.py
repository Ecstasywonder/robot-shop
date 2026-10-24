"""Run inside the pinned load image; exercise the workload without networking."""

import contextlib
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

from locust.env import Environment
from locust.stats import RequestStats


EXPECTED = {
    ("GET", "/"),
    ("POST", "/api/user/login"),
    ("GET", "/api/user/uniqueid"),
    ("GET", "/api/catalogue/categories"),
    ("GET", "/api/catalogue/products"),
    ("PUT", "/api/ratings/api/rate/{sku}/{rating}"),
    ("GET", "/api/catalogue/product/{sku}"),
    ("GET", "/api/ratings/api/fetch/{sku}"),
    ("GET", "/api/cart/add/{user_id}/{sku}/1"),
    ("GET", "/api/cart/cart/{user_id}"),
    ("GET", "/api/cart/update/{user_id}/{sku}/2"),
    ("GET", "/api/shipping/codes"),
    ("GET", "/api/shipping/cities/{country_code}"),
    ("GET", "/api/shipping/calc/{city_id}"),
    ("POST", "/api/shipping/confirm/{user_id}"),
    ("POST", "/api/payment/pay/{user_id}"),
    ("POST", "/api/payment/pay/partner-57"),
}


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data
        self.request_meta = {"response_time": 0, "response_length": 0}
        self.closed = False

    def json(self):
        return self.data

    def iter_content(self, chunk_size=1, decode_unicode=False):
        assert decode_unicode is False
        payload = json.dumps(self.data).encode("utf-8")
        for offset in range(0, len(payload), chunk_size):
            yield payload[offset : offset + chunk_size]

    def failure(self, message):
        raise AssertionError(message)

    def success(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FixtureClient:
    def __init__(self, stats):
        self.stats = stats
        self.sequence = 0

    def request(self, method, path, name=None, **kwargs):
        self.stats.log_request(method, name or path, 1, 0)
        if path == "/api/user/uniqueid":
            self.sequence += 1
            data = {"uuid": "fixture-user-{}".format(self.sequence)}
        elif path == "/api/catalogue/products":
            data = [{"sku": "fixture-sku-{}".format(self.sequence), "instock": 1}]
        elif path.startswith("/api/cart/cart/"):
            data = {"items": [{"sku": "fixture-sku-{}".format(self.sequence)}]}
        elif path == "/api/shipping/codes":
            data = [{"code": "fixture-country-{}".format(self.sequence), "name": "Fixture"}]
        elif path.startswith("/api/shipping/cities/"):
            data = [{"uuid": "fixture-city-{}".format(self.sequence), "name": "Fixture"}]
        else:
            data = {}
        return Response(data)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)


class FakeStop:
    def __init__(self, waits):
        self.waits = iter(waits)
        self.timeouts = []

    def wait(self, timeout):
        self.timeouts.append(timeout)
        return next(self.waits)


class FakeWorker:
    def __init__(self):
        self.finished = False
        self.joined = False
        self.killed = False

    def ready(self):
        return self.finished

    def join(self, timeout):
        self.joined = True
        self.finished = True

    def kill(self, block=False):
        self.killed = True
        self.finished = True


class FixtureEnvironment:
    def __init__(self, stats):
        self.stats = stats


def main():
    spec = importlib.util.spec_from_file_location("workload", sys.argv[1])
    workload = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workload)
    workload.randint = lambda lower, upper: lower
    workload.UserBehavior.host = "http://fixture.invalid"
    user = workload.UserBehavior(Environment())
    stats = RequestStats()
    user.client = FixtureClient(stats)
    os.environ["ERROR"] = "1"
    initial_keys = None
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
        for iteration in range(1000):
            user.load()
            user.login()
            user.error()
            keys = {(entry.method, entry.name) for entry in stats.entries.values()}
            if iteration == 0:
                initial_keys = keys
            if keys != EXPECTED or keys != initial_keys:
                raise AssertionError("Locust request-stat keys are not bounded route names")
    assert user.client.sequence == 1000

    spawned = []

    def fake_spawn(target, *args):
        worker = FakeWorker()
        spawned.append((target, args, worker))
        return worker

    workload.spawn = fake_spawn
    lifecycle_environment = FixtureEnvironment(stats)
    requests_before_start = sum(entry.num_requests for entry in stats.entries.values())
    workload.start_periodic_stats_reset(lifecycle_environment)
    workload.start_periodic_stats_reset(lifecycle_environment)
    assert len(spawned) == 1
    assert sum(entry.num_requests for entry in stats.entries.values()) == requests_before_start
    stopped_event = spawned[0][1][1]
    workload.stop_periodic_stats_reset(lifecycle_environment)
    assert stopped_event.is_set() and spawned[0][2].joined
    assert lifecycle_environment not in workload._stats_reset_workers
    workload.stop_periodic_stats_reset(lifecycle_environment)

    entry_ids = {key: id(entry) for key, entry in stats.entries.items()}
    stats.history.append({"fixture": True})
    stats.errors["fixture"] = object()
    stats.total.num_reqs_per_sec[123] = 1
    stopped = FakeStop([False, True])
    workload._reset_stats_periodically(SimpleNamespace(stats=stats), stopped)
    assert stopped.timeouts == [workload.STATS_RESET_SECONDS] * 2
    assert {key: id(entry) for key, entry in stats.entries.items()} == entry_ids
    assert all(entry.num_requests == 0 for entry in stats.entries.values())
    assert stats.history == []
    assert stats.errors == {}
    assert stats.total.num_reqs_per_sec == {}

    user.load()
    assert user.client.sequence == 1001
    assert {(entry.method, entry.name) for entry in stats.entries.values()} <= EXPECTED
    print(
        "PASS: 1000 distinct identities; 17 stable routes; hourly stats reset "
        "clears history, preserves entries, and traffic continues; no network"
    )


if __name__ == "__main__":
    main()

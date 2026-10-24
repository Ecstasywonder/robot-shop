"""Focused checks for the bounded city-array reader; run in the pinned load image."""

import importlib.util
import json
import random
import sys


def load_workload(path):
    spec = importlib.util.spec_from_file_location("workload", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StreamResponse:
    status_code = 200

    def __init__(self, payload, chunk_sizes=(16384,), status_code=200):
        self._payload = payload
        self._chunk_sizes = chunk_sizes
        self.status_code = status_code
        self.request_meta = {"response_time": 0, "response_length": 0}
        self.failure_message = None
        self.succeeded = False
        self.closed = False
        self.iterated = False

    @property
    def content(self):
        raise AssertionError("streaming reader accessed response.content")

    @property
    def text(self):
        raise AssertionError("streaming reader accessed response.text")

    def json(self):
        raise AssertionError("streaming reader accessed response.json()")

    def iter_content(self, chunk_size=1, decode_unicode=False):
        assert chunk_size > 0
        assert decode_unicode is False
        self.iterated = True
        offset = 0
        index = 0
        while offset < len(self._payload):
            size = self._chunk_sizes[index % len(self._chunk_sizes)]
            yield self._payload[offset : offset + size]
            offset += size
            index += 1

    def failure(self, message):
        self.failure_message = message

    def success(self):
        self.succeeded = True

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class StreamClient:
    def __init__(self, response):
        self.response = response
        self.path = None
        self.kwargs = None

    def get(self, path, **kwargs):
        self.path = path
        self.kwargs = kwargs
        return self.response


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def expect_error(workload, payload, expected, chunk_sizes=(1, 7, 19)):
    response = StreamResponse(payload, chunk_sizes=chunk_sizes)
    try:
        workload.stream_random_city(response)
    except workload.CityStreamError as exc:
        assert str(exc) == expected, (str(exc), expected)
        return response
    raise AssertionError("expected CityStreamError: {}".format(expected))


def check_valid_boundaries(workload):
    cities = [
        {
            "city": "Lagos",
            "code": "NG",
            "latitude": 6.45,
            "longitude": 3.39,
            "name": "Lagos ☂",
            "region": {"label": "La\\gos", "zones": [1, 2]},
            "uuid": 101,
        },
        {"uuid": "city-102", "name": "São Paulo", "nested": {"ok": True}},
    ]
    payload = b" \n\t" + encoded(cities) + b" \r\n"
    response = StreamResponse(payload, chunk_sizes=(1, 2, 3, 5, 8))
    selected, length = workload.stream_random_city(response, random_index=lambda low, high: 1)
    assert selected == cities[-1]
    assert length == len(payload)
    assert response.iterated


class RecordStream:
    def __init__(self, buffer, cursor=0, eof=True):
        self.buffer = buffer
        self.cursor = cursor
        self.eof = eof
        self.refills = 0

    def refill(self):
        self.refills += 1
        return False


class SpyDecoder:
    def __init__(self, decoder):
        self.decoder = decoder
        self.calls = []

    def raw_decode(self, text, index=0):
        self.calls.append((len(text), index))
        return self.decoder.raw_decode(text, index)


def check_record_fast_path(workload):
    city = {"uuid": 101, "name": "Lagos", "nested": {"zones": [1, 2]}}
    record = json.dumps(city, separators=(",", ":"))
    stream = RecordStream(record + ",")
    decoder = SpyDecoder(json.JSONDecoder())
    assert workload._read_city_record(stream, decoder) == city
    assert stream.cursor == len(record)
    assert decoder.calls == [(len(record) + 1, 0)]


def check_record_cross_chunk_fallback(workload):
    city = {"uuid": 102, "name": "São Paulo"}
    record = json.dumps(city, ensure_ascii=False, separators=(",", ":"))
    split = len(record) - 2
    stream = RecordStream(record[:split], eof=False)
    decoder = SpyDecoder(json.JSONDecoder())

    def refill():
        stream.refills += 1
        stream.buffer += record[split:]
        stream.eof = True
        return True

    stream.refill = refill
    assert workload._read_city_record(stream, decoder) == city
    assert stream.refills == 1
    # The incomplete fast-path attempt falls through to the one-pass framer.
    assert decoder.calls[0] == (split, 0)


def check_record_oversized_buffer_skips_fast_path(workload):
    city = {"uuid": 103, "name": "x" * (workload.MAX_CITY_RECORD_CHARS + 1)}
    stream = RecordStream(json.dumps(city, separators=(",", ":")))
    decoder = SpyDecoder(json.JSONDecoder())
    expect = "city entry exceeds size limit"
    try:
        workload._read_city_record(stream, decoder)
    except workload.CityStreamError as exc:
        assert str(exc) == expect
    else:
        raise AssertionError("expected CityStreamError: {}".format(expect))
    assert decoder.calls == []


def check_invalid_inputs(workload):
    cases = [
        (b"{}", "top-level value is not an array"),
        (b"[", "unexpected end of response"),
        (b"[]", "empty city array"),
        (b'[{"uuid":1,"name":"x"},]', "trailing comma"),
        (b'[{"uuid":1,"name":"x"}', "unexpected end of response"),
        (b'[{"uuid":1,"name":"x"}] junk', "trailing data"),
        (b'[{"uuid":1,"name":"x"}{"uuid":2,"name":"y"}]', "invalid array separator"),
        (b"[1]", "city entry is not an object"),
        (b'[{"uuid":true,"name":"x"}]', "city uuid is invalid"),
        (b'[{"uuid":1,"name":""}]', "city name is invalid"),
        (b'[{"uuid":1,"name":"\xff"}]', "invalid UTF-8"),
    ]
    for payload, expected in cases:
        expect_error(workload, payload, expected)

    oversized = encoded(
        {"uuid": 1, "name": "x" * (workload.MAX_CITY_RECORD_CHARS + 1)}
    )
    expect_error(workload, b"[" + oversized + b"]", "city entry exceeds size limit")


def check_reservoir_sampling(workload):
    cities = [{"uuid": number, "name": "city-{}".format(number)} for number in range(4)]
    payload = encoded(cities)
    generator = random.Random(20261023)
    counts = [0, 0, 0, 0]
    for _ in range(8000):
        response = StreamResponse(payload)
        selected, _ = workload.stream_random_city(response, random_index=generator.randint)
        counts[selected["uuid"]] += 1
    for count in counts:
        assert 1800 <= count <= 2200, counts


def check_locust_wrapper(workload):
    payload = encoded([{"uuid": 7, "name": "Abuja"}])
    response = StreamResponse(payload, chunk_sizes=(2, 1, 4))
    client = StreamClient(response)
    selected = workload.fetch_random_city(client, "NG", "192.0.2.10")
    assert selected == {"uuid": 7, "name": "Abuja"}
    assert client.path == "/api/shipping/cities/NG"
    assert client.kwargs["name"] == "/api/shipping/cities/{country_code}"
    assert client.kwargs["stream"] is True
    assert client.kwargs["catch_response"] is True
    assert response.succeeded and response.failure_message is None and response.closed
    assert response.request_meta["response_length"] == len(payload)
    assert response.request_meta["response_time"] >= 0

    http_response = StreamResponse(b"private-body", status_code=503)
    client = StreamClient(http_response)
    assert workload.fetch_random_city(client, "do-not-retain", "192.0.2.10") is None
    assert http_response.failure_message == "shipping cities HTTP 503"
    assert "do-not-retain" not in http_response.failure_message
    assert not http_response.iterated and http_response.closed

    bad_response = StreamResponse(b'[{"uuid":1}]', chunk_sizes=(2,))
    client = StreamClient(bad_response)
    assert workload.fetch_random_city(client, "do-not-retain", "192.0.2.10") is None
    assert bad_response.failure_message == "shipping cities city name is invalid"
    assert "do-not-retain" not in bad_response.failure_message
    assert bad_response.closed
    assert bad_response.request_meta["response_length"] == len(bad_response._payload)


def main():
    workload = load_workload(sys.argv[1])
    check_valid_boundaries(workload)
    check_record_fast_path(workload)
    check_record_cross_chunk_fallback(workload)
    check_record_oversized_buffer_skips_fast_path(workload)
    check_invalid_inputs(workload)
    check_reservoir_sampling(workload)
    check_locust_wrapper(workload)
    print(
        "PASS: strict chunked JSON, bounded records, fast-path fallback, uniform sampling, "
        "stable failures, metadata, and response closure"
    )


if __name__ == "__main__":
    main()

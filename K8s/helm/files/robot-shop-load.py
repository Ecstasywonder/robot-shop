import codecs
import json
import os
import random
import time

from gevent import spawn
from gevent.event import Event
from locust import HttpUser, between, events, task
from random import choice
from random import randint


CITY_STREAM_CHUNK_BYTES = 16 * 1024
MAX_CITY_RECORD_CHARS = 128 * 1024
STATS_RESET_SECONDS = 60 * 60
_stats_reset_workers = {}


class CityStreamError(ValueError):
    """A bounded, non-sensitive city-feed validation failure."""


def _reset_stats_periodically(environment, stopped, interval=STATS_RESET_SECONDS):
    while not stopped.wait(timeout=interval):
        environment.stats.reset_all()


@events.test_start.add_listener
def start_periodic_stats_reset(environment, **kwargs):
    current = _stats_reset_workers.get(environment)
    if current is not None and not current[1].ready():
        return
    stopped = Event()
    worker = spawn(_reset_stats_periodically, environment, stopped)
    _stats_reset_workers[environment] = (stopped, worker)


@events.test_stop.add_listener
def stop_periodic_stats_reset(environment, **kwargs):
    current = _stats_reset_workers.pop(environment, None)
    if current is None:
        return
    stopped, worker = current
    stopped.set()
    worker.join(timeout=1)
    if not worker.ready():
        worker.kill(block=False)


class _JsonTextStream:
    def __init__(self, response):
        self._chunks = response.iter_content(
            chunk_size=CITY_STREAM_CHUNK_BYTES, decode_unicode=False
        )
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self.buffer = ""
        self.cursor = 0
        self.eof = False
        self.bytes_read = 0

    def refill(self):
        if self.eof:
            return False

        # Drop parsed text only while refilling. This keeps the carry buffer
        # bounded without repeatedly copying it while JSONDecoder is scanning.
        if self.cursor:
            self.buffer = self.buffer[self.cursor :]
            self.cursor = 0

        while True:
            try:
                chunk = next(self._chunks)
            except StopIteration:
                try:
                    tail = self._decoder.decode(b"", final=True)
                except UnicodeDecodeError as exc:
                    raise CityStreamError("invalid UTF-8") from exc
                self.buffer += tail
                self.eof = True
                return bool(tail)

            if not chunk:
                continue
            if not isinstance(chunk, bytes):
                raise CityStreamError("invalid byte stream")
            self.bytes_read += len(chunk)
            response_meta = getattr(self, "_response_meta", None)
            if response_meta is not None:
                response_meta["response_length"] = self.bytes_read
            try:
                self.buffer += self._decoder.decode(chunk, final=False)
            except UnicodeDecodeError as exc:
                raise CityStreamError("invalid UTF-8") from exc
            return True

    def skip_whitespace(self):
        while True:
            while self.cursor < len(self.buffer) and self.buffer[self.cursor].isspace():
                self.cursor += 1
            if self.cursor < len(self.buffer) or self.eof:
                return
            self.refill()

    def next_non_whitespace(self):
        self.skip_whitespace()
        if self.cursor == len(self.buffer):
            return None
        value = self.buffer[self.cursor]
        self.cursor += 1
        return value


def _validate_city(city):
    if not isinstance(city, dict):
        raise CityStreamError("city entry is not an object")
    city_id = city.get("uuid")
    if isinstance(city_id, bool) or not isinstance(city_id, (int, str)):
        raise CityStreamError("city uuid is invalid")
    if not isinstance(city.get("name"), str) or not city["name"]:
        raise CityStreamError("city name is invalid")


def _read_city_record(stream, decoder):
    if stream.buffer[stream.cursor] != "{":
        raise CityStreamError("city entry is not an object")

    # Most city objects are entirely inside the current 16 KiB chunk. Let the
    # C JSON decoder find their boundary instead of framing every character in
    # Python. Do not try this when the carry buffer itself is oversized: the
    # streaming framer below must enforce the record limit in that case.
    remaining_chars = len(stream.buffer) - stream.cursor
    if remaining_chars <= MAX_CITY_RECORD_CHARS:
        try:
            city, record_end = decoder.raw_decode(stream.buffer, stream.cursor)
        except json.JSONDecodeError:
            pass
        else:
            stream.cursor = record_end
            return city

    pieces = []
    record_chars = 0
    depth = 0
    in_string = False
    escaped = False

    while True:
        segment_start = stream.cursor
        while stream.cursor < len(stream.buffer):
            char = stream.buffer[stream.cursor]
            stream.cursor += 1
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in "{[":
                depth += 1
            elif char in "}]":
                depth -= 1
                if depth == 0:
                    pieces.append(stream.buffer[segment_start : stream.cursor])
                    record_chars += stream.cursor - segment_start
                    if record_chars > MAX_CITY_RECORD_CHARS:
                        raise CityStreamError("city entry exceeds size limit")
                    record_text = "".join(pieces)
                    try:
                        city, record_end = decoder.raw_decode(record_text)
                    except json.JSONDecodeError as exc:
                        raise CityStreamError("invalid JSON") from exc
                    if record_end != len(record_text):
                        raise CityStreamError("invalid JSON")
                    return city
                if depth < 0:
                    raise CityStreamError("invalid JSON")

        pieces.append(stream.buffer[segment_start : stream.cursor])
        record_chars += stream.cursor - segment_start
        if record_chars > MAX_CITY_RECORD_CHARS:
            raise CityStreamError("city entry exceeds size limit")
        if stream.eof:
            raise CityStreamError("unexpected end of response")
        stream.refill()


def stream_random_city(response, random_index=randint):
    """Uniformly sample one object without retaining the JSON array."""
    stream = _JsonTextStream(response)
    stream._response_meta = getattr(response, "request_meta", None)
    decoder = json.JSONDecoder()
    if stream.next_non_whitespace() != "[":
        raise CityStreamError("top-level value is not an array")

    selected = None
    count = 0
    expect_value = True

    while True:
        stream.skip_whitespace()
        if stream.cursor == len(stream.buffer):
            if stream.eof:
                raise CityStreamError("unexpected end of response")
            stream.refill()
            continue

        if stream.buffer[stream.cursor] == "]":
            if expect_value and count:
                raise CityStreamError("trailing comma")
            stream.cursor += 1
            break
        if not expect_value:
            raise CityStreamError("missing comma")

        city = _read_city_record(stream, decoder)
        _validate_city(city)
        count += 1
        if random_index(1, count) == 1:
            selected = city
        expect_value = False

        separator = stream.next_non_whitespace()
        if separator == ",":
            expect_value = True
            continue
        if separator == "]":
            break
        if separator is None:
            raise CityStreamError("unexpected end of response")
        raise CityStreamError("invalid array separator")

    if not count:
        raise CityStreamError("empty city array")
    if stream.next_non_whitespace() is not None:
        raise CityStreamError("trailing data")
    return selected, stream.bytes_read


def fetch_random_city(client, country_code, fake_ip):
    path = "/api/shipping/cities/{}".format(country_code)
    started = time.perf_counter()
    with client.get(
        path,
        name="/api/shipping/cities/{country_code}",
        headers={"x-forwarded-for": fake_ip},
        stream=True,
        catch_response=True,
    ) as response:
        bytes_read = 0
        try:
            if not 200 <= response.status_code < 300:
                response.failure("shipping cities HTTP {}".format(response.status_code))
                return None
            city, bytes_read = stream_random_city(response)
        except CityStreamError as exc:
            response.failure("shipping cities {}".format(exc))
            return None
        finally:
            response.request_meta["response_time"] = (
                time.perf_counter() - started
            ) * 1000
            response.request_meta["response_length"] = max(
                bytes_read, response.request_meta.get("response_length", 0)
            )
            response.close()
        response.success()
        return city


class UserBehavior(HttpUser):
    wait_time = between(2, 10)

    # source: https://tools.tracemyip.org/search--ip/list
    fake_ip_addresses = [
        # white house
        "156.33.241.5",
        # Hollywood
        "34.196.93.245",
        # Chicago
        "98.142.103.241",
        # Los Angeles
        "192.241.230.151",
        # Berlin
        "46.114.35.116",
        # Singapore
        "52.77.99.130",
        # Sydney
        "60.242.161.215",
    ]

    def on_start(self):
        """on_start is called when a Locust starts before any task is scheduled."""
        print("Starting")

    @task
    def login(self):
        fake_ip = random.choice(self.fake_ip_addresses)

        credentials = {"name": "user", "password": "password"}
        res = self.client.post(
            "/api/user/login",
            json=credentials,
            headers={"x-forwarded-for": fake_ip},
        )
        print("login {}".format(res.status_code))

    @task
    def load(self):
        fake_ip = random.choice(self.fake_ip_addresses)

        self.client.get("/", headers={"x-forwarded-for": fake_ip})
        user = self.client.get(
            "/api/user/uniqueid", headers={"x-forwarded-for": fake_ip}
        ).json()
        uniqueid = user["uuid"]
        print("User {}".format(uniqueid))

        self.client.get(
            "/api/catalogue/categories", headers={"x-forwarded-for": fake_ip}
        )
        # all products in catalogue
        products = self.client.get(
            "/api/catalogue/products", headers={"x-forwarded-for": fake_ip}
        ).json()
        for _ in range(2):
            item = None
            while True:
                item = choice(products)
                if item["instock"] != 0:
                    break

            # vote for item
            if randint(1, 10) <= 3:
                self.client.put(
                    "/api/ratings/api/rate/{}/{}".format(
                        item["sku"], randint(1, 5)
                    ),
                    name="/api/ratings/api/rate/{sku}/{rating}",
                    headers={"x-forwarded-for": fake_ip},
                )

            self.client.get(
                "/api/catalogue/product/{}".format(item["sku"]),
                name="/api/catalogue/product/{sku}",
                headers={"x-forwarded-for": fake_ip},
            )
            self.client.get(
                "/api/ratings/api/fetch/{}".format(item["sku"]),
                name="/api/ratings/api/fetch/{sku}",
                headers={"x-forwarded-for": fake_ip},
            )
            self.client.get(
                "/api/cart/add/{}/{}/1".format(uniqueid, item["sku"]),
                name="/api/cart/add/{user_id}/{sku}/1",
                headers={"x-forwarded-for": fake_ip},
            )

        cart = self.client.get(
            "/api/cart/cart/{}".format(uniqueid),
            name="/api/cart/cart/{user_id}",
            headers={"x-forwarded-for": fake_ip},
        ).json()
        item = choice(cart["items"])
        self.client.get(
            "/api/cart/update/{}/{}/2".format(uniqueid, item["sku"]),
            name="/api/cart/update/{user_id}/{sku}/2",
            headers={"x-forwarded-for": fake_ip},
        )

        # country codes
        code = choice(
            self.client.get(
                "/api/shipping/codes", headers={"x-forwarded-for": fake_ip}
            ).json()
        )
        city = fetch_random_city(self.client, code["code"], fake_ip)
        if city is None:
            return
        print("code {} city {}".format(code, city))
        shipping = self.client.get(
            "/api/shipping/calc/{}".format(city["uuid"]),
            name="/api/shipping/calc/{city_id}",
            headers={"x-forwarded-for": fake_ip},
        ).json()
        shipping["location"] = "{} {}".format(code["name"], city["name"])
        print("Shipping {}".format(shipping))
        # POST
        cart = self.client.post(
            "/api/shipping/confirm/{}".format(uniqueid),
            name="/api/shipping/confirm/{user_id}",
            json=shipping,
            headers={"x-forwarded-for": fake_ip},
        ).json()
        print("Final cart {}".format(cart))

        order = self.client.post(
            "/api/payment/pay/{}".format(uniqueid),
            name="/api/payment/pay/{user_id}",
            json=cart,
            headers={"x-forwarded-for": fake_ip},
        ).json()
        print("Order {}".format(order))

    @task
    def error(self):
        fake_ip = random.choice(self.fake_ip_addresses)
        if os.environ.get("ERROR") == "1":
            print("Error request")
            cart = {"total": 0, "tax": 0}
            self.client.post(
                "/api/payment/pay/partner-57",
                json=cart,
                headers={"x-forwarded-for": fake_ip},
            )

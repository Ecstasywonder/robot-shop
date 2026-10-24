"""Isolated payment tracing check; no Kubernetes or external payment calls."""

import importlib.util
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class TraceReceiver(BaseHTTPRequestHandler):
    payloads = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.payloads.append(self.rfile.read(length))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return


class Response:
    def __init__(self, status_code):
        self.status_code = status_code


def load_payment(path):
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location("payment_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    receiver = ThreadingHTTPServer(("127.0.0.1", 0), TraceReceiver)
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    os.environ["OTEL_TRACING_ENABLED"] = "true"
    os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = (
        "http://127.0.0.1:{}/v1/traces".format(receiver.server_port)
    )

    payment = load_payment(sys.argv[1])
    payment.requests.get = lambda url, *args, **kwargs: Response(
        404 if "/check/" in url else 200
    )
    payment.requests.delete = lambda *args, **kwargs: Response(200)
    payment.publisher.publish = lambda *args, **kwargs: None

    response = payment.app.test_client().post(
        "/pay/fixture-user-not-a-span-attribute",
        json={"items": [{"sku": "SKU-NOT-A-SPAN-ATTRIBUTE", "qty": 1}, {"sku": "SHIP", "qty": 1}], "total": 7},
    )
    assert response.status_code == 200, response.data
    from opentelemetry import trace

    assert trace.get_tracer_provider().force_flush(3000)
    receiver.shutdown()
    receiver.server_close()

    payload = b"".join(TraceReceiver.payloads)
    assert b"payment.pay" in payload
    assert b"fixture-user-not-a-span-attribute" not in payload
    assert b"SKU-NOT-A-SPAN-ATTRIBUTE" not in payload
    print("PASS: manual payment span exported without request-derived attributes")


if __name__ == "__main__":
    main()

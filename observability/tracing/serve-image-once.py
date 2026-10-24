#!/usr/bin/env python3
"""Serve one exact file once to one exact private client."""

import argparse
import http.server
import os
import time


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.client_address[0] != self.server.allowed_client:
            self.send_error(403)
            return
        if self.path != self.server.allowed_path:
            self.send_error(404)
            return

        size = os.path.getsize(self.server.file_path)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(self.server.file_path, "rb") as archive:
            while True:
                chunk = archive.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
        self.server.completed = True

    def log_message(self, message, *args):
        print("{} {}".format(self.client_address[0], message % args), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--client", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    server = http.server.HTTPServer((args.bind, args.port), Handler)
    server.allowed_client = args.client
    server.allowed_path = args.path
    server.file_path = args.file
    server.completed = False
    server.timeout = 1
    deadline = time.monotonic() + 840
    while not server.completed and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if not server.completed:
        raise SystemExit("no authorized transfer completed before timeout")


if __name__ == "__main__":
    main()

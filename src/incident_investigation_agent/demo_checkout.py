"""Tiny checkout service. Each request is written to CloudWatch on Floci."""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from incident_investigation_agent.infrastructure.connectors.cloudwatch import logs_client

GROUP = os.environ.get("CHECKOUT_LOG_GROUP", "/aws/ecs/checkout-api")
STREAM = "api"
ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://floci:4566")
REGION = os.environ.get("AWS_REGION", "us-west-2")
PORT = int(os.environ.get("CHECKOUT_PORT", "8090"))


class _Writer:
    def __init__(self) -> None:
        self.client = logs_client(REGION, ENDPOINT)
        self.token = ""
        self._ready = False

    def emit(self, message: str) -> None:
        if not self._ready:
            self._open()
        kwargs = {
            "logGroupName": GROUP,
            "logStreamName": STREAM,
            "logEvents": [{"timestamp": int(time.time() * 1000), "message": message}],
        }
        if self.token:
            kwargs["sequenceToken"] = self.token
        page = self.client.put_log_events(**kwargs)
        self.token = str(page.get("nextSequenceToken") or "")

    def _open(self) -> None:
        try:
            self.client.create_log_group(logGroupName=GROUP)
        except Exception as exc:
            if exc.__class__.__name__ != "ResourceAlreadyExistsException":
                raise
        try:
            self.client.create_log_stream(logGroupName=GROUP, logStreamName=STREAM)
        except Exception as exc:
            if exc.__class__.__name__ != "ResourceAlreadyExistsException":
                raise
        page = self.client.describe_log_streams(logGroupName=GROUP, logStreamNamePrefix=STREAM)
        streams = page.get("logStreams") or []
        if streams:
            self.token = str(streams[0].get("uploadSequenceToken") or "")
        self._ready = True


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


writer = _Writer()


class CheckoutHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/logs":
            self._logs()
            return
        if self.path != "/checkout":
            self._send(404, {"error": "not found"})
            return
        self._checkout()

    def do_POST(self) -> None:
        if self.path != "/checkout":
            self._send(404, {"error": "not found"})
            return
        self._checkout()

    def _logs(self) -> None:
        events = writer.client.filter_log_events(logGroupName=GROUP, limit=20).get("events") or []
        items = "\n".join(f"<li>{_escape(str(event.get('message', '')))}</li>" for event in events)
        if not items:
            items = "<li>No lines in this group yet.</li>"
        page = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Checkout logs</title></head>
<body style="font-family: sans-serif; max-width: 46rem; margin: 2rem;">
<h1>Lines in /aws/ecs/checkout-api</h1>
<p>These are the messages stored in Floci CloudWatch. The case file reads this same group.</p>
<ul>
{items}
</ul>
</body>
</html>
"""
        self._html(200, page)

    def _checkout(self) -> None:
        first = 'checkout-api ERROR upstream payments-api status=500 body="card vault timeout"'
        second = "checkout-api ERROR request POST /checkout status=500 latency_ms=3010"
        writer.emit(first)
        writer.emit(second)
        page = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Checkout failed</title></head>
<body style="font-family: sans-serif; max-width: 40rem; margin: 2rem;">
<h1>Checkout failed</h1>
<p>This service returned an error and wrote two lines to CloudWatch on Floci, group <code>/aws/ecs/checkout-api</code>.</p>
<ul>
<li>{first}</li>
<li>{second}</li>
</ul>
<p>Go back to <a href="http://localhost:8080">the case file</a> and click Investigate on the checkout case. Those lines are what it reads.</p>
</body>
</html>
"""
        raw = page.encode()
        self.send_response(500)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _html(self, status: int, page: str) -> None:
        raw = page.encode()
        self.send_response(status)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:
        print(f"checkout {self.address_string()} {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), CheckoutHandler)
    print(f"checkout listening on {PORT}, writing to {GROUP} at {ENDPOINT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Local static server + Jira CORS proxy for planning.html."""

from __future__ import annotations

import argparse
import http.client
import ssl
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DEFAULT_JIRA = "https://mars-jira.systemgroup.net"
PROXY_PREFIX = "/jira-proxy"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, jira_base: str, **kwargs):
        self.jira_base = jira_base.rstrip("/")
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, Accept, X-Requested-With",
        )
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith(PROXY_PREFIX):
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith(PROXY_PREFIX):
            self._proxy()
        else:
            self.send_error(405)

    def do_PUT(self):
        if self.path.startswith(PROXY_PREFIX):
            self._proxy()
        else:
            self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith(PROXY_PREFIX):
            self._proxy()
        else:
            self.send_error(405)

    def _proxy(self):
        suffix = self.path[len(PROXY_PREFIX) :] or "/"
        target = f"{self.jira_base}{suffix}"
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(target, data=body, method=self.command)
        # Forward auth + accept headers only (avoid hop-by-hop headers)
        for name in ("Authorization", "Accept", "Content-Type"):
            value = self.headers.get(name)
            if value:
                req.add_header(name, value)

        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                data = resp.read()
                self.send_response(resp.status)
                content_type = resp.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            content_type = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            msg = str(e).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description="Serve planning.html with Jira CORS proxy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--jira", default=DEFAULT_JIRA, help="Jira base URL")
    args = parser.parse_args()

    jira = args.jira.rstrip("/")
    parsed = urlparse(jira)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"Invalid --jira URL: {jira}")

    def factory(*a, **kw):
        return Handler(*a, jira_base=jira, **kw)

    server = ThreadingHTTPServer((args.host, args.port), factory)
    print(f"Planning app:  http://{args.host}:{args.port}/planning.html")
    print(f"Jira proxy:    http://{args.host}:{args.port}{PROXY_PREFIX}/ → {jira}/")
    print("Keep this terminal open while using the app.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

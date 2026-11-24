#!/usr/bin/env python3
"""Local Sprint Room static server, sprint-file API, and Jira/OpenRouter proxy."""

from __future__ import annotations

import argparse
import http.client
import json
import re
import ssl
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "dist" / "browser" if (ROOT / "dist" / "browser").exists() else ROOT
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DATA_LOCK = threading.Lock()
DEFAULT_JIRA = "https://mars-jira.systemgroup.net"
PROXY_PREFIX = "/jira-proxy"
OPENROUTER_PREFIX = "/openrouter-proxy"
OPENROUTER_BASE = "https://openrouter.ai"
FORWARD_HEADERS = ("Authorization", "Accept", "Content-Type", "X-Title", "HTTP-Referer")


def _legacy_slugify(title):
    title = re.sub(r"[\\/]+", " ", str(title or "").strip())
    title = re.sub(r"\s+", "-", title)
    title = re.sub(r"[^\w\-\.\u0600-\u06ff]", "", title, flags=re.UNICODE)
    return title.strip("-_.")[:100]


def migrate_legacy_sprints():
    """Bring older folder-based planner exports into the new data library once."""
    for source in ROOT.glob("*/*.json"):
        if source.parent == DATA_DIR or source.parent == ROOT:
            continue
        try:
            record = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        title = str((record.get("plan") or {}).get("sprintName") or "").strip()
        slug = _legacy_slugify(title)
        if not slug:
            continue
        target = DATA_DIR / f"{slug}.json"
        if target.exists():
            continue
        try:
            stamp = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
            record["_meta"] = {"title": title, "slug": slug, "createdAt": stamp, "updatedAt": stamp}
            target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            continue


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, jira_base: str, **kwargs):
        self.jira_base = jira_base.rstrip("/")
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, Accept, X-Requested-With, X-Title, X-Upstream-Base",
        )
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _route(self):
        """Return (upstream base, path suffix, timeout) for proxied requests."""
        if self.path.startswith(PROXY_PREFIX):
            return self.jira_base, self.path[len(PROXY_PREFIX) :] or "/", 30
        if self.path.startswith(OPENROUTER_PREFIX):
            # The page sends its configured gateway so internal reverse proxies work too
            base = (self.headers.get("X-Upstream-Base") or "").strip().rstrip("/")
            parsed = urlparse(base)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                base = OPENROUTER_BASE
            return base, self.path[len(OPENROUTER_PREFIX) :] or "/", 180
        return None

    def do_GET(self):
        if self.path == "/api/sprints" or self.path.startswith("/api/sprints/"):
            self._handle_sprint_api()
        elif self._route():
            self._proxy()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/sprints":
            self._handle_sprint_api()
        elif self._route():
            self._proxy()
        else:
            self.send_error(405)

    def do_PUT(self):
        if self.path.startswith("/api/sprints/"):
            self._handle_sprint_api()
        elif self._route():
            self._proxy()
        else:
            self.send_error(405)

    def do_DELETE(self):
        if self._route():
            self._proxy()
        else:
            self.send_error(405)

    def _json_response(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _request_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 12 * 1024 * 1024:
            raise ValueError("payload is too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _slugify(title):
        title = re.sub(r"[\\/]+", " ", str(title or "").strip())
        title = re.sub(r"\s+", "-", title)
        title = re.sub(r"[^\w\-\.\u0600-\u06ff]", "", title, flags=re.UNICODE)
        return title.strip("-_.")[:100]

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _sprint_path(self, slug):
        clean = self._slugify(unquote(slug).removesuffix(".json"))
        if not clean or ".." in clean or clean != unquote(slug).removesuffix(".json"):
            return None
        return DATA_DIR / f"{clean}.json"

    @staticmethod
    def _summary(path, data):
        plan = data.get("plan") or {}
        members = data.get("members") or []
        tasks = data.get("tasks") or []
        completed = sum(1 for task in tasks if task.get("dod") in {"Analyzed", "Implemented", "Merged"})
        allocated = 0.0
        for task in tasks:
            for role in ("backend", "backendReview", "frontend", "frontendReview", "tester", "analyst"):
                allocated += float((task.get(role) or {}).get("hours") or 0)
            allocated += float(task.get("generalHours") or 0)
        capacity = sum(float(member.get("capacity") or 0) for member in members)
        meta = data.get("_meta") or {}
        title = str(meta.get("title") or plan.get("sprintName") or path.stem)
        return {
            "slug": path.stem,
            "title": title,
            "fileName": path.name,
            "createdAt": meta.get("createdAt") or "",
            "updatedAt": meta.get("updatedAt") or "",
            "startDate": str(plan.get("startDate") or ""),
            "endDate": str(plan.get("endDate") or ""),
            "members": len(members),
            "tasks": len(tasks),
            "completedTasks": completed,
            "allocatedHours": round(allocated, 1),
            "capacityHours": round(capacity, 1),
        }

    def _handle_sprint_api(self):
        try:
            if self.command == "GET" and self.path == "/api/sprints":
                rows = []
                with DATA_LOCK:
                    for path in sorted(DATA_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
                        try:
                            rows.append(self._summary(path, json.loads(path.read_text(encoding="utf-8"))))
                        except (OSError, ValueError, TypeError):
                            continue
                return self._json_response({"sprints": rows})

            if self.command == "POST" and self.path == "/api/sprints":
                payload = self._request_json()
                title = str(payload.get("title") or "").strip() if isinstance(payload, dict) else ""
                slug = self._slugify(title)
                if not title or not slug:
                    return self._json_response({"error": "عنوان اسپرینت الزامی است"}, 400)
                path = DATA_DIR / f"{slug}.json"
                if path.exists():
                    return self._json_response({"error": "اسپرینتی با این نام وجود دارد"}, 409)
                template = {}
                template_path = ROOT / "general_data.json"
                if template_path.exists():
                    template = json.loads(template_path.read_text(encoding="utf-8"))
                template.setdefault("plan", {})["sprintName"] = title
                template.setdefault("jiraConfig", {})
                template.setdefault("aiConfig", {})
                template.setdefault("members", [])
                template.setdefault("tasks", [])
                now = self._now()
                template["_meta"] = {"title": title, "slug": slug, "createdAt": now, "updatedAt": now}
                path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return self._json_response(self._summary(path, template), 201)

            prefix = "/api/sprints/"
            raw_slug = self.path[len(prefix):].split("?", 1)[0] if self.path.startswith(prefix) else ""
            path = self._sprint_path(raw_slug)
            if path is None:
                return self._json_response({"error": "invalid sprint name"}, 400)
            if self.command == "GET":
                if not path.exists():
                    return self._json_response({"error": "sprint not found"}, 404)
                return self._json_response(json.loads(path.read_text(encoding="utf-8")))
            if self.command == "PUT":
                if not path.exists():
                    return self._json_response({"error": "sprint not found"}, 404)
                payload = self._request_json()
                if not isinstance(payload, dict):
                    return self._json_response({"error": "invalid JSON object"}, 400)
                existing = json.loads(path.read_text(encoding="utf-8"))
                meta = existing.get("_meta") or {}
                payload["_meta"] = {
                    "title": meta.get("title") or (payload.get("plan") or {}).get("sprintName") or path.stem,
                    "slug": path.stem,
                    "createdAt": meta.get("createdAt") or self._now(),
                    "updatedAt": self._now(),
                }
                with DATA_LOCK:
                    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return self._json_response(self._summary(path, payload))
            if self.command == "POST":
                return self._json_response({"error": "invalid route"}, 400)
            return self._json_response({"error": "method not allowed"}, 405)
        except json.JSONDecodeError:
            return self._json_response({"error": "invalid JSON"}, 400)
        except ValueError as error:
            return self._json_response({"error": str(error)}, 400)
        except OSError as error:
            return self._json_response({"error": f"storage error: {error}"}, 500)

    def _proxy(self):
        base, suffix, timeout = self._route()
        target = f"{base}{suffix}"
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None

        req = urllib.request.Request(target, data=body, method=self.command)
        # Forward auth + accept headers only (avoid hop-by-hop headers)
        for name in FORWARD_HEADERS:
            value = self.headers.get(name)
            if value:
                req.add_header(name, value)

        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
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
    parser = argparse.ArgumentParser(
        description="Serve index.html with Jira + OpenRouter CORS proxy"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--jira", default=DEFAULT_JIRA, help="Jira base URL")
    args = parser.parse_args()

    migrate_legacy_sprints()

    jira = args.jira.rstrip("/")
    parsed = urlparse(jira)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit(f"Invalid --jira URL: {jira}")

    def factory(*a, **kw):
        return Handler(*a, jira_base=jira, **kw)

    server = ThreadingHTTPServer((args.host, args.port), factory)
    print(f"Planning app:  http://{args.host}:{args.port}/index.html")
    print(f"Jira proxy:    http://{args.host}:{args.port}{PROXY_PREFIX}/ → {jira}/")
    print(
        f"OpenRouter:    http://{args.host}:{args.port}{OPENROUTER_PREFIX}/ → {OPENROUTER_BASE}/"
    )
    print("Keep this terminal open while using the app.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

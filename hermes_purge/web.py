"""Loopback control panel: host/origin checks, bearer token, bounded JSON input."""
from __future__ import annotations

import hmac
import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from . import armor, scrub
from .core import DEFAULT_PRESET, DEFAULT_PROMPT, PRESETS, PurgeError


def armor_status():
    """Sealed prompt inventory plus the scrub rule table (no live counters: the panel is a
    separate process from the agent that runs the armor)."""
    return {
        "default_set": armor.DEFAULT_SET,
        "prompt_sets": [{"name": item.name, "label": item.label,
                         "chars": len(armor.prompt_text(item.name)),
                         "default": item.name == armor.DEFAULT_SET}
                        for item in armor.prompt_sets()],
        "scrub_rules": scrub.rule_report(),
        "refusal_recover": {
            "note": "Continuation rides the next request via the llm_request middleware; "
                    "counters live in the agent process (see /purge armor).",
        },
    }


def make_server(manager, port=0, token=None):
    token = token or secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *args):
            pass

        def reply(self, status, payload, html=False):
            data = payload if html else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def check(self, api=False):
            authority = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != authority:
                self.reply(403, {"error": "Host mismatch"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{authority}":
                self.reply(403, {"error": "Origin mismatch"})
                return False
            if api and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self.reply(401, {"error": "Token required"})
                return False
            return True

        def do_GET(self):
            if not self.check(api=self.path != "/"):
                return
            try:
                if self.path == "/":
                    self.reply(200, Path(__file__).with_name("panel.html").read_bytes(), html=True)
                elif self.path == "/api/status":
                    self.reply(200, {"state": manager.status(), "presets": list(PRESETS),
                                     "default_preset": DEFAULT_PRESET,
                                     "default_prompt": DEFAULT_PROMPT,
                                     "armor": armor_status()})
                else:
                    self.reply(404, {"error": "Not found"})
            except (PurgeError, OSError, ValueError) as exc:
                self.reply(409, {"error": str(exc)})

        def do_POST(self):
            if not self.check(api=True):
                return
            try:
                if self.headers.get_content_type() != "application/json":
                    raise PurgeError("application/json required")
                if self.headers.get("Transfer-Encoding"):
                    raise PurgeError("Transfer-Encoding is not supported")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise PurgeError("JSON body must contain 1-65536 bytes")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise PurgeError("JSON object required")
                allowed = {"preset", "prompt", "prompt_set", "approval_mode", "max_iterations",
                           "expected_sha256"}
                if set(body) - allowed:
                    raise PurgeError("Unknown option")
                expected = body.pop("expected_sha256", None)
                if self.path == "/api/plan":
                    result = manager.plan(**body).public()
                elif self.path == "/api/apply":
                    if not isinstance(expected, str):
                        raise PurgeError("Preview hash is required before applying")
                    result = manager.apply(expected_sha256=expected, **body)
                elif self.path == "/api/revert":
                    if body:
                        raise PurgeError("Revert takes no options")
                    result = manager.revert()
                else:
                    self.reply(404, {"error": "Not found"})
                    return
                self.reply(200, result)
            except (PurgeError, OSError, ValueError, TypeError) as exc:
                self.reply(409, {"error": str(exc)})

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    # Limit slow clients without using a multi-threaded shared profile context.
    original_get_request = server.get_request
    def get_request():
        sock, address = original_get_request()
        sock.settimeout(5)
        return sock, address
    server.get_request = get_request
    return server, token


def serve(manager, port=8765, open_browser=False):
    server, token = make_server(manager, port)
    url = f"http://127.0.0.1:{server.server_port}/#{token}"
    print(url, flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

"""
interview.relay.server
----------------------
Self-contained relay HTTP server. Pure stdlib — no external dependencies.

Implements the contract defined in docs/relay-api.md.

Usage:
  python -m interview.relay.server --port 8080 --data /data

Environment variables:
  RELAY_API_KEY   Required. Shared secret for all requests.
  RELAY_DATA_DIR  Data directory (default: /data). Override with --data.
  RELAY_PORT      Port (default: 8080). Override with --port.
"""

import argparse
import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from interview.relay.store import SessionStore, StoreError

# ─── Globals (set at startup) ─────────────────────────────────────────────────

_store: SessionStore | None = None
_api_key: str = ""


# ─── Handler ──────────────────────────────────────────────────────────────────

class RelayHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress default access log; use our own
        print(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else ''}")

    # ── auth ──────────────────────────────────────────────────────────────────

    def _auth(self) -> bool:
        if not _api_key:
            return True  # no key configured → open (dev mode)
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {_api_key}"

    # ── response helpers ──────────────────────────────────────────────────────

    def _json(self, data, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str | bytes, content_type: str = "text/plain", status: int = 200):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str):
        self._json({"error": code, "message": message}, status)

    def _read_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return None

    # ── routing ───────────────────────────────────────────────────────────────

    def _route(self) -> tuple[str, list[str]]:
        """Return (path_without_query, path_segments)."""
        parsed = urlparse(self.path)
        parts  = [p for p in parsed.path.strip("/").split("/") if p]
        return parsed.path, parts

    def do_GET(self):
        if not self._auth():
            return self._error(401, "unauthorized", "Invalid or missing API key.")
        _, parts = self._route()

        # GET /sessions
        if parts == ["sessions"]:
            return self._get_sessions()

        # GET /sessions/<code>
        if len(parts) == 2 and parts[0] == "sessions":
            return self._get_session(parts[1])

        # GET /sessions/<code>/report.html
        if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "report.html":
            return self._get_file(parts[1], "report.html", "text/html")

        # GET /sessions/<code>/events
        if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "events":
            return self._get_file(parts[1], "events.jsonl", "text/plain")

        # GET /audit/verify
        if parts == ["audit", "verify"]:
            return self._get_audit_verify()

        self._error(404, "not_found", f"No route for GET {self.path}")

    def do_POST(self):
        if not self._auth():
            return self._error(401, "unauthorized", "Invalid or missing API key.")
        _, parts = self._route()

        # POST /sessions
        if parts == ["sessions"]:
            return self._post_session()

        # POST /sessions/<code>/<action>
        if len(parts) == 3 and parts[0] == "sessions":
            action = parts[2]
            code   = parts[1]
            if action == "grade":
                return self._post_grade(code)
            if action == "reveal":
                return self._post_reveal(code)
            if action == "comment":
                return self._post_comment(code)
            if action == "decision":
                return self._post_decision(code)

        self._error(404, "not_found", f"No route for POST {self.path}")

    # ── GET handlers ──────────────────────────────────────────────────────────

    def _get_sessions(self):
        self._json(_store.list_sessions())

    def _get_session(self, code: str):
        session = _store.get_session(code)
        if not session:
            return self._error(404, "session_not_found", f"No session for {code}.")
        self._json(session)

    def _get_file(self, code: str, filename: str, content_type: str):
        data = _store.get_file(code, filename)
        if data is None:
            return self._error(404, "file_not_found", f"{filename} not found for {code}.")
        self._text(data, content_type)

    def _get_audit_verify(self):
        self._json(_store.verify_all_chains())

    # ── POST handlers ─────────────────────────────────────────────────────────

    def _post_session(self):
        body = self._read_body()
        if body is None:
            return self._error(400, "invalid_payload", "Could not parse JSON body.")

        code = body.get("code", "").strip()
        if not code:
            return self._error(400, "invalid_payload", "Missing 'code' field.")

        if _store.exists(code):
            return self._error(409, "already_exists", f"Session {code} already submitted.")

        # Decode base64 files
        file_map = {
            "manifest.json":  "manifest_json",
            "events.jsonl":   "events_jsonl",
            "report.html":    "report_html",
            "report.json":    "report_json",
        }
        missing = [k for k in ["manifest_json", "events_jsonl"] if k not in body]
        if missing:
            return self._error(400, "invalid_payload",
                               f"Required fields missing: {', '.join(missing)}")

        files: dict[str, bytes] = {}
        for fname, key in file_map.items():
            if key in body:
                try:
                    files[fname] = base64.b64decode(body[key])
                except Exception:
                    return self._error(400, "invalid_payload",
                                       f"Could not base64-decode '{key}'.")

        _store.save_session(code, files)
        self._json({"code": code, "submitted_at": _store._load_meta(code).get("submitted_at")},
                   status=201)

    def _post_grade(self, code: str):
        if not _store.exists(code):
            return self._error(404, "session_not_found", f"No session for {code}.")
        body = self._read_body()
        if body is None:
            return self._error(400, "invalid_payload", "Could not parse JSON body.")
        if "overall_score" not in body or "dimensions" not in body:
            return self._error(400, "invalid_payload",
                               "Grading payload must include 'overall_score' and 'dimensions'.")
        try:
            result = _store.save_grade(code, body)
            self._json(result)
        except StoreError as e:
            if str(e) == "already_graded":
                self._error(409, "already_graded", "Grade already recorded for this session.")
            else:
                self._error(500, "store_error", str(e))

    def _post_reveal(self, code: str):
        if not _store.exists(code):
            return self._error(404, "session_not_found", f"No session for {code}.")
        try:
            result = _store.record_reveal(code)
            self._json(result)
        except StoreError as e:
            if str(e) == "not_graded":
                self._error(403, "not_graded",
                            "Cannot reveal identity before grade is recorded.")
            else:
                self._error(500, "store_error", str(e))

    def _post_comment(self, code: str):
        if not _store.exists(code):
            return self._error(404, "session_not_found", f"No session for {code}.")
        body = self._read_body()
        if not body or not body.get("text", "").strip():
            return self._error(400, "invalid_payload", "Missing 'text' field.")
        result = _store.add_comment(code, body["text"].strip())
        self._json(result)

    def _post_decision(self, code: str):
        if not _store.exists(code):
            return self._error(404, "session_not_found", f"No session for {code}.")
        body = self._read_body()
        decision = (body or {}).get("decision", "")
        if decision not in ("hire", "next_round", "reject"):
            return self._error(400, "invalid_payload",
                               "decision must be 'hire', 'next_round', or 'reject'.")
        try:
            result = _store.save_decision(code, decision, (body or {}).get("reason", ""))
            self._json(result)
        except StoreError as e:
            if str(e) == "already_decided":
                self._error(409, "already_decided", "Decision already recorded.")
            else:
                self._error(500, "store_error", str(e))


# ─── Entry point ──────────────────────────────────────────────────────────────

def start_relay(port: int = 8080, data_dir: Path = Path("/data")):
    global _store, _api_key

    _api_key = os.environ.get("RELAY_API_KEY", "")
    if not _api_key:
        print("⚠  RELAY_API_KEY not set — relay is running in open mode (dev only).")

    _store = SessionStore(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("0.0.0.0", port), RelayHandler)
    print(f"\n  interviewsignal relay")
    print(f"  ─────────────────────────────────────────")
    print(f"  Listening on  http://0.0.0.0:{port}")
    print(f"  Data dir      {data_dir}")
    print(f"  Auth          {'API key set' if _api_key else 'OPEN (set RELAY_API_KEY)'}")
    print(f"  ─────────────────────────────────────────\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Relay stopped.")


def main():
    parser = argparse.ArgumentParser(description="interviewsignal relay server")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("RELAY_PORT", 8080)))
    parser.add_argument("--data", type=Path,
                        default=Path(os.environ.get("RELAY_DATA_DIR", "/data")))
    args = parser.parse_args()
    start_relay(port=args.port, data_dir=args.data)


if __name__ == "__main__":
    main()

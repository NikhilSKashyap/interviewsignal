"""
interview.relay.server
----------------------
Multi-tenant relay HTTP server. Pure stdlib — no external dependencies.

Auth model:
  POST /register              — open (no auth)
  GET  /interviews/<code>     — open (public package fetch)
  All other routes            — Bearer <hm_key> required

Usage:
  python -m interview.relay.server --port 8080 --data /data

Environment variables:
  RELAY_API_KEY   Optional master key (for self-hosted operator access).
  RELAY_DATA_DIR  Data directory (default: /data).
  RELAY_PORT      Port (default: 8080).
"""

import argparse
import base64
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from interview.relay.store import SessionStore, StoreError, make_cid

_store: SessionStore | None = None
_relay_api_key: str = ""


class RelayHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else ''}")

    # ── auth ──────────────────────────────────────────────────────────────────

    def _bearer(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return ""

    def _auth_hm(self) -> str | None:
        """
        Validate bearer token as an hm_key.
        Returns the hm_key if valid, None otherwise.
        Also accepts the master relay_api_key for operator access.
        """
        token = self._bearer()
        if not token:
            return None
        if _relay_api_key and token == _relay_api_key:
            return token  # operator access
        if _store.hm_exists(token):
            return token
        return None

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

    def _parts(self) -> list[str]:
        parsed = urlparse(self.path)
        return [p for p in parsed.path.strip("/").split("/") if p]

    def do_GET(self):
        parts = self._parts()

        # Open routes — no auth
        if len(parts) == 2 and parts[0] == "interviews":
            return self._get_interview(parts[1])

        # Auth-gated routes
        hm_key = self._auth_hm()
        if hm_key is None:
            return self._error(401, "unauthorized", "Valid hm_key required.")

        if parts == ["sessions"]:
            return self._get_sessions(hm_key)

        if len(parts) == 2 and parts[0] == "sessions":
            return self._get_session_list(hm_key, parts[1])

        if len(parts) == 3 and parts[0] == "sessions":
            return self._get_session(hm_key, parts[1], parts[2])

        if len(parts) == 4 and parts[0] == "sessions":
            action = parts[3]
            if action == "events":
                return self._get_file(hm_key, parts[1], parts[2], "events.jsonl", "text/plain")
            if action == "report.html":
                return self._get_file(hm_key, parts[1], parts[2], "report.html", "text/html")

        if parts == ["audit", "verify"]:
            return self._get_audit_verify(hm_key)

        self._error(404, "not_found", f"No route for GET {self.path}")

    def do_POST(self):
        parts = self._parts()

        # Open route
        if parts == ["register"]:
            return self._post_register()

        # Auth-gated routes
        hm_key = self._auth_hm()
        if hm_key is None:
            return self._error(401, "unauthorized", "Valid hm_key required.")

        if parts == ["interviews"]:
            return self._post_interview(hm_key)

        if parts == ["sessions"]:
            return self._post_session(hm_key)

        if len(parts) == 4 and parts[0] == "sessions":
            action = parts[3]
            code, cid = parts[1], parts[2]
            if action == "grade":
                return self._post_grade(hm_key, code, cid)
            if action == "reveal":
                return self._post_reveal(hm_key, code, cid)
            if action == "comment":
                return self._post_comment(hm_key, code, cid)
            if action == "decision":
                return self._post_decision(hm_key, code, cid)

        self._error(404, "not_found", f"No route for POST {self.path}")

    # ── open GET handlers ─────────────────────────────────────────────────────

    def _get_interview(self, code: str):
        payload = _store.get_interview(code)
        if payload is None:
            return self._error(404, "not_found", f"No interview for code {code}.")
        self._json(payload)

    # ── open POST handlers ────────────────────────────────────────────────────

    def _post_register(self):
        hm_key = _store.register_hm()
        self._json({"hm_key": hm_key}, status=201)

    # ── auth GET handlers ─────────────────────────────────────────────────────

    def _get_sessions(self, hm_key: str):
        interviews = _store.list_interviews(hm_key)
        self._json({"interviews": interviews})

    def _get_session_list(self, hm_key: str, code: str):
        candidates = _store._summarise_candidates(hm_key, code)
        self._json({"code": code, "candidates": candidates})

    def _get_session(self, hm_key: str, code: str, cid: str):
        session = _store.get_session(hm_key, code, cid)
        if not session:
            return self._error(404, "session_not_found", f"No session for {code}/{cid}.")
        self._json(session)

    def _get_file(self, hm_key: str, code: str, cid: str, filename: str, content_type: str):
        data = _store.get_file(hm_key, code, cid, filename)
        if data is None:
            return self._error(404, "file_not_found", f"{filename} not found for {code}/{cid}.")
        self._text(data, content_type)

    def _get_audit_verify(self, hm_key: str):
        self._json(_store.verify_all_chains(hm_key))

    # ── auth POST handlers ────────────────────────────────────────────────────

    def _post_interview(self, hm_key: str):
        body = self._read_body()
        if body is None:
            return self._error(400, "invalid_payload", "Could not parse JSON body.")
        code = body.get("code", "").strip()
        payload_b64 = body.get("payload_b64", "").strip()
        if not code or not payload_b64:
            return self._error(400, "invalid_payload", "Missing 'code' or 'payload_b64'.")
        try:
            payload = json.loads(base64.b64decode(payload_b64.encode()))
        except Exception:
            return self._error(400, "invalid_payload", "Could not decode payload_b64.")
        try:
            _store.register_interview(hm_key, code, payload)
        except StoreError as e:
            if str(e) == "already_exists":
                return self._error(409, "already_exists", f"Interview {code} already registered.")
            return self._error(500, "store_error", str(e))
        import time
        self._json({"code": code, "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, status=201)

    def _post_session(self, hm_key: str):
        body = self._read_body()
        if body is None:
            return self._error(400, "invalid_payload", "Could not parse JSON body.")

        code = body.get("code", "").strip()
        candidate_email = body.get("candidate_email", "").strip()
        if not code or not candidate_email:
            return self._error(400, "invalid_payload", "Missing 'code' or 'candidate_email'.")

        # Validate code belongs to this HM
        owner = _store.lookup_hm_for_code(code)
        if owner is None:
            return self._error(404, "interview_not_found",
                               f"Interview {code} not registered. HM must push /interviews first.")
        if owner != hm_key:
            return self._error(403, "forbidden", "This code belongs to a different HM.")

        cid = make_cid(candidate_email)
        if _store.session_exists(hm_key, code, cid):
            return self._error(409, "already_submitted",
                               f"{candidate_email} has already submitted for {code}.")

        file_map = {
            "manifest.json": "manifest_json",
            "events.jsonl":  "events_jsonl",
            "report.html":   "report_html",
            "report.json":   "report_json",
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

        _store.save_session(hm_key, code, cid, candidate_email, files)
        import time
        self._json({
            "code":         code,
            "cid":          cid,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, status=201)

    def _post_grade(self, hm_key: str, code: str, cid: str):
        if not _store.session_exists(hm_key, code, cid):
            return self._error(404, "session_not_found", f"No session for {code}/{cid}.")
        body = self._read_body()
        if body is None:
            return self._error(400, "invalid_payload", "Could not parse JSON body.")
        if "overall_score" not in body or "dimensions" not in body:
            return self._error(400, "invalid_payload",
                               "Grading payload must include 'overall_score' and 'dimensions'.")
        try:
            result = _store.save_grade(hm_key, code, cid, body)
            self._json(result)
        except StoreError as e:
            if str(e) == "already_graded":
                self._error(409, "already_graded", "Grade already recorded.")
            else:
                self._error(500, "store_error", str(e))

    def _post_reveal(self, hm_key: str, code: str, cid: str):
        if not _store.session_exists(hm_key, code, cid):
            return self._error(404, "session_not_found", f"No session for {code}/{cid}.")
        try:
            self._json(_store.record_reveal(hm_key, code, cid))
        except StoreError as e:
            if str(e) == "not_graded":
                self._error(403, "not_graded", "Cannot reveal before grade is recorded.")
            else:
                self._error(500, "store_error", str(e))

    def _post_comment(self, hm_key: str, code: str, cid: str):
        if not _store.session_exists(hm_key, code, cid):
            return self._error(404, "session_not_found", f"No session for {code}/{cid}.")
        body = self._read_body()
        if not body or not body.get("text", "").strip():
            return self._error(400, "invalid_payload", "Missing 'text' field.")
        self._json(_store.add_comment(hm_key, code, cid, body["text"].strip()))

    def _post_decision(self, hm_key: str, code: str, cid: str):
        if not _store.session_exists(hm_key, code, cid):
            return self._error(404, "session_not_found", f"No session for {code}/{cid}.")
        body = self._read_body() or {}
        decision = body.get("decision", "")
        if decision not in ("hire", "next_round", "reject"):
            return self._error(400, "invalid_payload",
                               "decision must be 'hire', 'next_round', or 'reject'.")
        try:
            self._json(_store.save_decision(hm_key, code, cid, decision, body.get("reason", "")))
        except StoreError as e:
            if str(e) == "already_decided":
                self._error(409, "already_decided", "Decision already recorded.")
            else:
                self._error(500, "store_error", str(e))


# ─── Entry point ──────────────────────────────────────────────────────────────

def start_relay(port: int = 8080, data_dir: Path = Path("/data")):
    global _store, _relay_api_key

    _relay_api_key = os.environ.get("RELAY_API_KEY", "")
    if not _relay_api_key:
        print("⚠  RELAY_API_KEY not set — master key disabled (dev mode).")

    _store = SessionStore(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("0.0.0.0", port), RelayHandler)
    print(f"\n  interviewsignal relay")
    print(f"  ─────────────────────────────────────────")
    print(f"  Listening on  http://0.0.0.0:{port}")
    print(f"  Data dir      {data_dir}")
    print(f"  Master key    {'set' if _relay_api_key else 'not set (dev mode)'}")
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

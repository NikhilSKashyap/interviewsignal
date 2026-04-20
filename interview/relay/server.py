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
import hmac
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from html import escape as _esc
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request as _Req, urlopen as _urlopen
from urllib.error import URLError

from interview.relay.store import SessionStore, StoreError, make_cid, make_github_cid
from interview.core.grader import DEFAULT_GRADING_MODEL

# ─── Environment variables ────────────────────────────────────────────────────
# RELAY_API_KEY     — HM registration key (required in production)
# GRADING_API_KEY   — Anthropic API key for auto-grading (optional)
# GRADING_MODEL     — Model for auto-grading (default: claude-haiku-4-5-20251001)
# GITHUB_CLIENT_ID  — GitHub OAuth app client ID (optional)
# GITHUB_CLIENT_SECRET — GitHub OAuth app client secret (optional)
# RELAY_BASE_URL    — Public base URL of this relay (optional, for OAuth redirect URIs)
# RELAY_DATA_DIR    — Data directory (default: /data)
# RELAY_PORT / PORT — Port to listen on (default: 8080)

_store: SessionStore | None = None
_relay_api_key: str = ""
_github_client_id: str = ""
_github_client_secret: str = ""
_relay_base_url: str = ""


def _github_configured() -> bool:
    return bool(_github_client_id and _github_client_secret)


# ─── GitHub API helpers ───────────────────────────────────────────────────────

def _exchange_github_code(oauth_code: str) -> dict:
    """Exchange GitHub OAuth code for an access token. Returns parsed JSON."""
    data = urlencode({
        "client_id":     _github_client_id,
        "client_secret": _github_client_secret,
        "code":          oauth_code,
    }).encode()
    req = _Req(
        "https://github.com/login/oauth/access_token",
        data=data,
        headers={"Accept": "application/json"},
    )
    with _urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _fetch_github_profile(access_token: str) -> dict:
    """Fetch the authenticated GitHub user's profile."""
    req = _Req(
        "https://api.github.com/user",
        headers={
            "Authorization":        f"Bearer {access_token}",
            "Accept":               "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent":           "interviewsignal",
        },
    )
    with _urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ─── OAuth HTML response pages ────────────────────────────────────────────────

def _oauth_success_html(github_username: str) -> str:
    uname = _esc(github_username)
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><title>Authenticated — interviewsignal</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
background:#0f0f0f;color:#e0e0e0;display:flex;align-items:center;
justify-content:center;height:100vh}}
.box{{text-align:center;padding:48px 40px;border:1px solid #2a2a2a;
border-radius:14px;background:#161616;max-width:400px}}
h2{{color:#4ade80;font-size:22px;margin-bottom:12px}}
p{{color:#888;font-size:14px;line-height:1.6}}
strong{{color:#e0e0e0}}</style></head>
<body><div class="box">
<h2>&#10003; Authenticated</h2>
<p>Signed in as <strong>@{uname}</strong></p>
<p style="margin-top:16px">Return to your terminal to continue.</p>
</div></body></html>"""


def _oauth_error_html(message: str) -> str:
    msg = _esc(message)
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><title>Authentication Failed — interviewsignal</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
background:#0f0f0f;color:#e0e0e0;display:flex;align-items:center;
justify-content:center;height:100vh}}
.box{{text-align:center;padding:48px 40px;border:1px solid #2a2a2a;
border-radius:14px;background:#161616;max-width:400px}}
h2{{color:#f87171;font-size:22px;margin-bottom:12px}}
p{{color:#888;font-size:14px;line-height:1.6}}</style></head>
<body><div class="box">
<h2>&#10007; Authentication Failed</h2>
<p>{msg}</p>
<p style="margin-top:16px">Close this tab and try again.</p>
</div></body></html>"""


def _oauth_duplicate_html(github_username: str, code: str) -> str:
    uname = _esc(github_username)
    ecode = _esc(code)
    return f"""<!DOCTYPE html><html lang="en">
<head><meta charset="UTF-8"><title>Already Submitted — interviewsignal</title>
<style>*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
background:#0f0f0f;color:#e0e0e0;display:flex;align-items:center;
justify-content:center;height:100vh}}
.box{{text-align:center;padding:48px 40px;border:1px solid #2a2a2a;
border-radius:14px;background:#161616;max-width:420px}}
h2{{color:#f59e0b;font-size:22px;margin-bottom:12px}}
p{{color:#888;font-size:14px;line-height:1.6}}
strong{{color:#e0e0e0}}</style></head>
<body><div class="box">
<h2>&#9888; Already Submitted</h2>
<p><strong>@{uname}</strong> has already submitted for <strong>{ecode}</strong>.</p>
<p style="margin-top:16px">Each GitHub account can submit once per interview.</p>
</div></body></html>"""


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
        # Use constant-time comparison for the master key to prevent timing attacks.
        if _relay_api_key and hmac.compare_digest(token, _relay_api_key):
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

        # Health check — open, no auth
        if not parts or parts == ["healthz"]:
            return self._json({"status": "ok"})

        # GitHub OAuth routes — open, no auth
        if len(parts) >= 2 and parts[0] == "auth" and parts[1] == "github":
            action = parts[2] if len(parts) > 2 else ""
            if action == "start":
                return self._get_github_start()
            if action == "callback":
                return self._get_github_callback()
            if action == "poll":
                return self._get_github_poll()
            return self._error(404, "not_found", f"No route for GET {self.path}")

        # Open routes — no auth
        if len(parts) == 2 and parts[0] == "interviews":
            return self._get_interview(parts[1])

        # Score endpoint — open (candidate fetches own score by knowing their cid)
        if len(parts) == 4 and parts[0] == "sessions" and parts[3] == "score":
            return self._get_score_open(parts[1], parts[2])

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
            if action == "sharing":
                return self._get_sharing(hm_key, parts[1])

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

        # Sharing config update — parts[2] is code, no cid
        if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "sharing":
            return self._post_sharing(hm_key, parts[1])

        self._error(404, "not_found", f"No route for POST {self.path}")

    # ── open GET handlers ─────────────────────────────────────────────────────

    def _get_interview(self, code: str):
        # Look up the hm_key so we can call get_interview_candidate()
        hm_key = _store.lookup_hm_for_code(code)
        if hm_key is None:
            return self._error(404, "not_found", f"No interview for code {code}.")
        # Return only candidate-safe fields — rubric never leaves the relay
        candidate_pkg = _store.get_interview_candidate(hm_key, code)
        if candidate_pkg is None:
            return self._error(404, "not_found", f"No interview for code {code}.")
        self._json(candidate_pkg)

    def _get_relay_base(self) -> str:
        """Best-effort relay base URL for building redirect_uri."""
        if _relay_base_url:
            return _relay_base_url.rstrip("/")
        host = self.headers.get("Host", "localhost:8080")
        # Assume HTTPS unless it's obviously a local dev host
        scheme = "http" if host.startswith("localhost") or host.startswith("127.") else "https"
        return f"{scheme}://{host}"

    def _get_github_start(self):
        """
        GET /auth/github/start?code=INT-4829-XK
        Returns {url, state} for the candidate CLI to open in a browser.
        Returns 501 if GitHub OAuth is not configured on this relay.
        """
        if not _github_configured():
            return self._json({
                "github_configured": False,
                "message": "GitHub OAuth not configured on this relay.",
            }, 501)

        params = parse_qs(urlparse(self.path).query)
        code = params.get("code", [""])[0].strip()
        if not code:
            return self._error(400, "missing_code", "Missing 'code' query parameter.")
        if not _store.lookup_hm_for_code(code):
            return self._error(404, "interview_not_found", f"Interview {code} not found.")

        state = str(uuid.uuid4())
        _store.save_github_state(state, code)

        redirect_uri = f"{self._get_relay_base()}/auth/github/callback"
        qs = urlencode({
            "client_id":    _github_client_id,
            "redirect_uri": redirect_uri,
            "scope":        "read:user",
            "state":        state,
        })
        self._json({"url": f"https://github.com/login/oauth/authorize?{qs}", "state": state})

    def _get_github_callback(self):
        """
        GET /auth/github/callback?code=<oauth_code>&state=<state>
        GitHub redirects here after the candidate authorizes.
        Exchanges the code, fetches the profile, stores the result, returns HTML.
        """
        params = parse_qs(urlparse(self.path).query)
        oauth_code = params.get("code", [""])[0]
        state      = params.get("state", [""])[0]

        if not oauth_code or not state:
            return self._text(_oauth_error_html("Missing code or state parameter."), "text/html", 400)

        state_data = _store.get_github_state(state)
        if not state_data or state_data.get("status") != "pending":
            return self._text(_oauth_error_html("Invalid or expired state. Please try again."), "text/html", 400)

        if time.time() - state_data.get("created_at", 0) > 300:
            _store.update_github_state(state, {"status": "expired"})
            return self._text(_oauth_error_html("Session expired. Run /interview <CODE> again."), "text/html", 400)

        # Exchange OAuth code for access token
        try:
            token_data = _exchange_github_code(oauth_code)
        except Exception as e:
            _store.update_github_state(state, {"status": "error", "error": str(e)})
            return self._text(_oauth_error_html(f"GitHub token exchange failed: {e}"), "text/html", 500)

        access_token = token_data.get("access_token", "")
        if not access_token:
            err = token_data.get("error_description") or token_data.get("error") or "No access_token in response"
            _store.update_github_state(state, {"status": "error", "error": err})
            return self._text(_oauth_error_html(f"GitHub auth failed: {err}"), "text/html", 400)

        # Fetch user profile
        try:
            profile = _fetch_github_profile(access_token)
        except Exception as e:
            _store.update_github_state(state, {"status": "error", "error": str(e)})
            return self._text(_oauth_error_html(f"Could not fetch GitHub profile: {e}"), "text/html", 500)

        github_id       = profile.get("id")
        github_username = profile.get("login", "")
        avatar_url      = profile.get("avatar_url", "")
        interview_code  = state_data["code"]

        # Duplicate check — early warning in browser (enforced again on submit)
        if _store.check_github_duplicate(interview_code, github_id):
            _store.update_github_state(state, {
                "status":          "duplicate",
                "github_username": github_username,
            })
            return self._text(_oauth_duplicate_html(github_username, interview_code), "text/html")

        # Success
        _store.update_github_state(state, {
            "status":          "complete",
            "github_id":       github_id,
            "github_username": github_username,
            "github_name":     profile.get("name") or github_username,
            "avatar_url":      avatar_url,
            "access_token":    access_token,
        })
        return self._text(_oauth_success_html(github_username), "text/html")

    def _get_github_poll(self):
        """
        GET /auth/github/poll?state=<state>
        Candidate CLI polls this until status == "complete" or a terminal state.
        """
        params = parse_qs(urlparse(self.path).query)
        state  = params.get("state", [""])[0]
        if not state:
            return self._error(400, "missing_state", "Missing 'state' query parameter.")

        state_data = _store.get_github_state(state)
        if not state_data:
            return self._error(404, "not_found", "Unknown state token.")

        status = state_data.get("status", "pending")

        if status == "pending":
            if time.time() - state_data.get("created_at", 0) > 300:
                _store.update_github_state(state, {"status": "expired"})
                return self._json({"status": "expired"})
            return self._json({"status": "pending"})

        if status == "complete":
            return self._json({
                "status":          "complete",
                "github_id":       state_data.get("github_id"),
                "github_username": state_data.get("github_username"),
                "github_name":     state_data.get("github_name", state_data.get("github_username")),
                "avatar_url":      state_data.get("avatar_url"),
                # state UUID doubles as the session_token — relay looks it up by state
                "session_token":   state,
                "github_token":    state_data.get("access_token"),
            })

        if status == "duplicate":
            return self._json({
                "status":          "duplicate",
                "github_username": state_data.get("github_username"),
                "message":         "You have already submitted for this interview.",
            })

        # error / expired
        return self._json({"status": status, "error": state_data.get("error", "")})

    # ── open POST handlers ────────────────────────────────────────────────────

    def _post_register(self):
        self._read_body()  # drain request body (required for keep-alive correctness)
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

    def _get_sharing(self, hm_key: str, code: str):
        """GET /sessions/{code}/<anything>/sharing — return current sharing config."""
        if not _store.lookup_hm_for_code(code):
            return self._error(404, "interview_not_found", f"No interview for code {code}.")
        config = _store.get_sharing_config(hm_key, code)
        self._json({"code": code, "sharing": config})

    def _get_score_open(self, code: str, cid: str):
        """
        GET /sessions/{code}/{cid}/score — open route.
        Candidate fetches their own score by knowing their cid.
        Response is filtered by the HM's sharing config.
        """
        hm_key = _store.lookup_hm_for_code(code)
        if hm_key is None:
            return self._error(404, "interview_not_found", f"No interview for code {code}.")
        result = _store.get_score_response(hm_key, code, cid)
        if result is None:
            return self._error(404, "session_not_found", f"No session for {code}/{cid}.")
        self._json(result)

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

    # Base64 adds ~33% overhead; 200 MB gives headroom above the 100 MB session limit.
    _MAX_SESSION_BODY = 200 * 1024 * 1024

    def _post_session(self, hm_key: str):
        # Check Content-Length BEFORE reading the body to prevent OOM on huge requests.
        try:
            body_len = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            body_len = 0
        if body_len > self._MAX_SESSION_BODY:
            return self._error(
                413, "payload_too_large",
                f"Request body too large ({body_len // 1024 // 1024} MB). Limit: 200 MB.",
            )
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

        # ── GitHub identity resolution ─────────────────────────────────────────
        github_identity: dict | None = None
        session_token = body.get("session_token", "").strip()

        if _github_configured():
            if not session_token:
                return self._error(
                    401, "github_auth_required",
                    "This relay requires GitHub authentication. "
                    "Run /interview <CODE> to authenticate before submitting.",
                )
            state_data = _store.get_github_state(session_token)
            if not state_data or state_data.get("status") != "complete":
                return self._error(401, "invalid_session_token",
                                   "Invalid or expired GitHub session token.")
            if state_data.get("code") != code:
                return self._error(403, "token_mismatch",
                                   "Session token was issued for a different interview code.")
            github_id = state_data.get("github_id")
            if _store.check_github_duplicate(code, github_id):
                return self._error(409, "already_submitted",
                                   "This GitHub account has already submitted for this interview.")
            github_identity = {
                "github_id":       github_id,
                "github_username": state_data.get("github_username"),
                "avatar_url":      state_data.get("avatar_url"),
            }
            cid = make_github_cid(github_id)
        else:
            # No GitHub configured — use email-based cid (existing behaviour)
            cid = make_cid(candidate_email)

        if _store.session_exists(hm_key, code, cid):
            return self._error(409, "already_submitted",
                               f"A session for this candidate already exists for {code}.")

        file_map = {
            "manifest.json": "manifest_json",
            "events.jsonl":  "events_jsonl",
            "report.html":   "report_html",
            "report.json":   "report_json",
            "debrief.txt":   "debrief_txt",
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

        github_repo_url = body.get("github_repo_url") or None
        candidate_name  = body.get("candidate_name") or None
        _store.save_session(hm_key, code, cid, candidate_email, files,
                            github_identity=github_identity,
                            github_repo_url=github_repo_url,
                            candidate_name=candidate_name)

        # --- Auto-grading (best-effort, non-fatal) ---
        grading_api_key = os.environ.get("GRADING_API_KEY", "").strip()
        if grading_api_key:
            try:
                auto_grade_flag = _store.get_auto_grade(hm_key, code)
                if auto_grade_flag:
                    rubric = _store.get_rubric(hm_key, code)
                    if rubric:
                        # Load the just-saved session data (events + manifest from relay store)
                        session_data = _store.get_session(hm_key, code, cid)
                        events = session_data.get("events", [])
                        manifest = session_data.get("manifest", {})
                        grading_model = os.environ.get("GRADING_MODEL", DEFAULT_GRADING_MODEL)
                        from interview.core.grader import grade_session_from_data
                        grade = grade_session_from_data(
                            events=events,
                            manifest=manifest,
                            rubric=rubric,
                            api_key=grading_api_key,
                            model=grading_model,
                        )
                        if grade:
                            _store.save_grade(hm_key, code, cid, grade, graded_by="auto")
            except Exception as e:
                print(f"[auto-grade] {code}/{cid}: {e}", flush=True)
        # --- end auto-grading ---

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
            if _store.is_graded(hm_key, code, cid):
                # Revision — requires a reason explaining the change
                reason = (body.get("reason") or "").strip()
                if not reason:
                    return self._error(400, "revision_requires_reason",
                                       "Grade revision requires a 'reason' field explaining the change.")
                result = _store.revise_grade(hm_key, code, cid, body, reason)
                self._json(result)
            else:
                result = _store.save_grade(hm_key, code, cid, body)
                self._json(result)
        except StoreError as e:
            return self._error(500, "store_error", str(e))

    def _post_reveal(self, hm_key: str, code: str, cid: str):
        self._read_body()  # drain request body
        if not _store.session_exists(hm_key, code, cid):
            return self._error(404, "session_not_found", f"No session for {code}/{cid}.")
        try:
            self._json(_store.record_reveal(hm_key, code, cid))
        except StoreError as e:
            return self._error(500, "store_error", str(e))

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
                return self._error(409, "already_decided", "Decision already recorded.")
            else:
                return self._error(500, "store_error", str(e))

    def _post_sharing(self, hm_key: str, code: str):
        """POST /sessions/{code}/sharing — update sharing config for an interview code."""
        if not _store.lookup_hm_for_code(code):
            return self._error(404, "interview_not_found", f"No interview for code {code}.")
        body = self._read_body()
        if body is None:
            return self._error(400, "invalid_payload", "Could not parse JSON body.")
        sharing = body.get("sharing", body)  # accept {sharing: {...}} or the dict itself
        score = sharing.get("score", "none")
        if score not in ("none", "overall", "breakdown", "breakdown_notes"):
            return self._error(400, "invalid_payload",
                               "sharing.score must be: none | overall | breakdown | breakdown_notes")
        config = {"score": score}
        _store.save_sharing_config(hm_key, code, config)
        self._json({"code": code, "sharing": config})


# ─── Entry point ──────────────────────────────────────────────────────────────

def start_relay(port: int = 8080, data_dir: Path = Path("/data")):
    global _store, _relay_api_key, _github_client_id, _github_client_secret, _relay_base_url

    _relay_api_key = os.environ.get("RELAY_API_KEY", "")
    if not _relay_api_key:
        print("⚠  RELAY_API_KEY not set — master key disabled (dev mode).")

    _github_client_id     = os.environ.get("GITHUB_CLIENT_ID", "")
    _github_client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "")
    _relay_base_url       = os.environ.get("RELAY_BASE_URL", "").rstrip("/")

    _store = SessionStore(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("0.0.0.0", port), RelayHandler)
    print(f"\n  interviewsignal relay")
    print(f"  ─────────────────────────────────────────")
    print(f"  Listening on  http://0.0.0.0:{port}")
    print(f"  Data dir      {data_dir}")
    print(f"  Master key    {'set' if _relay_api_key else 'not set (dev mode)'}")
    print(f"  GitHub OAuth  {'enabled' if _github_configured() else 'not configured'}")
    if _relay_base_url:
        print(f"  Base URL      {_relay_base_url}")
    print(f"  ─────────────────────────────────────────\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Relay stopped.")


def main():
    parser = argparse.ArgumentParser(description="interviewsignal relay server")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT", os.environ.get("RELAY_PORT", 8080))))
    parser.add_argument("--data", type=Path,
                        default=Path(os.environ.get("RELAY_DATA_DIR", "/data")))
    args = parser.parse_args()
    start_relay(port=args.port, data_dir=args.data)


if __name__ == "__main__":
    main()

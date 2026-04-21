"""
interview.core.transport
------------------------
Transport layer abstraction. Decouples session delivery and retrieval
from the underlying mechanism (email vs. relay).

Config-driven — no code changes needed to switch:
  ~/.interview/config.json:
    relay_url + hm_key set  → RelayTransport (multi-tenant hosted relay)
    relay_url only           → RelayTransport (self-hosted, master key auth)
    neither                  → EmailTransport (SMTP send, local file read)

Public surface:
  get_transport()                    → returns the right Transport for current config
  transport.send(code)               → candidate: deliver sealed session to HM
  transport.list_sessions()          → HM dashboard: list available sessions
  transport.get_session(code, cid)   → HM dashboard: fetch one session detail
  transport.post_action(...)         → HM dashboard: grade / reveal / comment / decision
  transport.get_interview(code)      → candidate: fetch interview package from relay
  RelayTransport.register_hm(url)    → static: register and get hm_key

All relay calls use stdlib urllib only — no external dependencies.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR  = INTERVIEW_DIR / "sessions"
RECEIVED_DIR  = INTERVIEW_DIR / "received"
CONFIG_FILE   = INTERVIEW_DIR / "config.json"


# ─── Config helpers ───────────────────────────────────────────────────────────

def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def get_relay_url() -> str | None:
    return _load_config().get("relay_url", "").rstrip("/") or None


def get_relay_api_key() -> str:
    return _load_config().get("relay_api_key", "")


def get_hm_key() -> str:
    return _load_config().get("hm_key", "")


def set_hm_key(hm_key: str):
    """Atomically write hm_key to config.json."""
    config = _load_config()
    config["hm_key"] = hm_key
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.replace(CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def is_transport_configured() -> bool:
    """True if either relay or SMTP is configured."""
    config = _load_config()
    has_relay = bool(config.get("relay_url", "").strip())
    has_smtp  = bool(config.get("smtp_host", "").strip())
    return has_relay or has_smtp


# ─── Abstract base ────────────────────────────────────────────────────────────

class Transport(ABC):

    @abstractmethod
    def send(self, code: str) -> bool:
        """Candidate-side: deliver the sealed session. Returns True on success."""

    @abstractmethod
    def list_sessions(self) -> list[dict]:
        """HM dashboard: return flat list of session summaries."""

    @abstractmethod
    def get_session(self, code: str, cid: str | None = None) -> dict | None:
        """HM dashboard: return full session detail, or None if not found."""

    @abstractmethod
    def post_action(self, code: str, action: str, payload: dict, cid: str | None = None) -> dict:
        """HM dashboard: POST a state-changing action."""

    def get_interview(self, code: str) -> dict | None:
        """Candidate: fetch interview package by code. None if not found."""
        return None

    def get_score(self, code: str, cid: str) -> dict | None:
        """Candidate: fetch their own score. None if not available."""
        return None


class TransportError(Exception):
    """Raised by transport methods when an operation fails unrecoverably."""


# ─── Email transport (local fallback) ────────────────────────────────────────

class EmailTransport(Transport):
    """
    Local-first transport.
    - send()           → SMTP via email_sender.send_report()
    - list_sessions()  → reads ~/.interview/received/*.json
    - get_session()    → reads ~/.interview/received/<code>.json
    - post_action()    → applies locally via decisions / audit modules
    """

    def send(self, code: str) -> bool:
        from interview.core.email_sender import send_report
        return send_report(code)

    def list_sessions(self) -> list[dict]:
        if not RECEIVED_DIR.exists():
            return []
        sessions = []
        for f in sorted(RECEIVED_DIR.glob("*.json"), reverse=True):
            try:
                sessions.append(json.loads(f.read_text()))
            except Exception:
                pass
        return sessions

    def get_session(self, code: str, cid: str | None = None) -> dict | None:
        f = RECEIVED_DIR / f"{code}.json"
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text())
        except Exception:
            return None

    def post_action(self, code: str, action: str, payload: dict, cid: str | None = None) -> dict:
        if action == "grade":
            from interview.core.decisions import save_grade
            return save_grade(code, payload)
        elif action == "reveal":
            from interview.core.decisions import record_reveal
            return record_reveal(code)
        elif action == "comment":
            from interview.core.decisions import add_comment
            return add_comment(code, payload.get("text", ""))
        elif action == "decision":
            from interview.core.decisions import record_decision
            return record_decision(code, payload.get("decision"), payload.get("reason", ""))
        raise TransportError(f"Unknown action: {action}")

    def get_score(self, code: str, cid: str) -> dict | None:
        return None


# ─── Relay transport ──────────────────────────────────────────────────────────

class RelayTransport(Transport):
    """
    Multi-tenant relay transport.

    Auth: hm_key is the per-HM bearer token (from POST /register).
    Fallback: relay_api_key used if hm_key not set (self-hosted operator access).

    Candidate submit falls back to EmailTransport if relay is unreachable.
    """

    def __init__(self, relay_url: str, hm_key: str = "", api_key: str = ""):
        self.relay_url = relay_url.rstrip("/")
        self.hm_key    = hm_key
        self.api_key   = api_key   # master relay_api_key (self-hosted fallback)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        token = self.hm_key or self.api_key
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        timeout: int = 30,
    ) -> dict | list | str:
        url = f"{self.relay_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                ct  = resp.headers.get("Content-Type", "")
                if "text/html" in ct:
                    return raw.decode()
                if "text/plain" in ct:
                    return raw.decode()
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:300]
            raise TransportError(f"Relay {method} {path} → {e.code}: {body_text}")
        except Exception as e:
            raise TransportError(f"Relay {method} {path} failed: {e}")

    # ── Registration (static — no auth needed) ────────────────────────────────

    @staticmethod
    def register_hm(relay_url: str) -> str:
        """
        POST /register — open route, returns hm_key.
        Raises TransportError on failure.
        """
        url = relay_url.rstrip("/") + "/register"
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                hm_key = data.get("hm_key", "")
                if not hm_key:
                    raise TransportError("Registration response missing hm_key.")
                return hm_key
        except TransportError:
            raise
        except Exception as e:
            raise TransportError(f"Registration failed: {e}")

    # ── Interview package (open route — no auth header) ───────────────────────

    def get_interview(self, code: str) -> dict | None:
        """
        GET /interviews/<code> — open route, no auth header sent.
        Returns the interview payload dict, or None if not found.
        """
        url = f"{self.relay_url}/interviews/{code}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise TransportError(f"GET /interviews/{code} → {e.code}")
        except Exception as e:
            raise TransportError(f"GET /interviews/{code} failed: {e}")

    def push_interview(self, code: str, payload: dict) -> dict:
        """POST /interviews — push an interview package to the relay."""
        payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        result = self._request("POST", "/interviews", body={"code": code, "payload_b64": payload_b64})
        return result if isinstance(result, dict) else {}

    # ── Candidate submit ──────────────────────────────────────────────────────

    def send(self, code: str) -> bool:
        session_dir = SESSIONS_DIR / code
        manifest_path = session_dir / "manifest.json"

        if not manifest_path.exists():
            print(f"✗ Cannot submit: manifest.json missing for {code}.")
            return False

        manifest = json.loads(manifest_path.read_text())
        candidate_email = manifest.get("candidate_email", "")
        if not candidate_email:
            print("⚠ No candidate_email in manifest — falling back to email.")
            return EmailTransport().send(code)

        body: dict = {"code": code, "candidate_email": candidate_email}
        if manifest.get("session_token"):
            body["session_token"] = manifest["session_token"]
        if manifest.get("github_repo_url"):
            body["github_repo_url"] = manifest["github_repo_url"]
        if manifest.get("candidate_name"):
            body["candidate_name"] = manifest["candidate_name"]
        if manifest.get("github_username"):
            body["github_username"] = manifest["github_username"]
        file_map = {
            "manifest_json": "manifest.json",
            "events_jsonl":  "events.jsonl",
            "report_html":   "report.html",
            "report_json":   "report.json",
            "debrief_txt":   "debrief.txt",
        }
        for key, fname in file_map.items():
            f = session_dir / fname
            if f.exists():
                body[key] = base64.b64encode(f.read_bytes()).decode()

        if "manifest_json" not in body or "events_jsonl" not in body:
            print(f"✗ Cannot submit: required files missing for {code}.")
            return False

        try:
            result = self._request("POST", "/sessions", body=body, timeout=60)
            print(f"✓ Session submitted to relay: {self.relay_url}")
            # Return relay response dict so callers can inspect auto_graded flag
            return result if isinstance(result, dict) else True
        except TransportError as e:
            err = str(e)
            if "github_auth_required" in err or "invalid_session_token" in err:
                # Relay requires GitHub authentication — email fallback would bypass
                # identity verification, so we hard-stop here instead.
                print(f"✗ Relay submission blocked: GitHub authentication required.")
                print(f"  Your session was started without GitHub auth.")
                print(f"  Start a new session with /interview <CODE> to authenticate properly.")
                return False
            if "already_submitted" in err:
                # This GitHub account already has a submission on the relay.
                # Email fallback would create a duplicate under a different identity — block it.
                print(f"✗ Already submitted: your GitHub account has already submitted for this interview.")
                print(f"  Only one submission per interview is allowed.")
                return False
            print(f"⚠ Relay submission failed: {e}")
            print(f"  Falling back to email...")
            return EmailTransport().send(code)

    # ── HM dashboard ──────────────────────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        """
        Returns a flat list of candidate summaries for the dashboard.
        Each entry includes 'code' and 'cid' alongside session metadata.
        """
        try:
            result = self._request("GET", "/sessions")
            if not isinstance(result, dict):
                return []
            flat = []
            for interview in result.get("interviews", []):
                code  = interview.get("code", "")
                title = interview.get("title", "")
                for candidate in interview.get("candidates", []):
                    entry = dict(candidate)
                    entry["code"]  = code
                    entry["title"] = title
                    entry.setdefault("_source", "relay")
                    entry.setdefault("_anonymize", interview.get("anonymize", False))
                    flat.append(entry)
            return flat
        except TransportError:
            return []

    def get_session(self, code: str, cid: str | None = None) -> dict | None:
        if cid:
            path = f"/sessions/{code}/{cid}"
        else:
            # No cid: list candidates for this code, return first
            path = f"/sessions/{code}"
        try:
            result = self._request("GET", path)
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return result[0] if result else None
            return None
        except TransportError:
            return None

    def post_action(self, code: str, action: str, payload: dict, cid: str | None = None) -> dict:
        if cid:
            path = f"/sessions/{code}/{cid}/{action}"
        else:
            # Legacy path (email-mode compatibility; shouldn't be hit in relay mode)
            path = f"/sessions/{code}/{action}"
        try:
            result = self._request("POST", path, body=payload)
            return result if isinstance(result, dict) else {}
        except TransportError as e:
            raise TransportError(f"Action '{action}' failed: {e}")

    def get_score(self, code: str, cid: str) -> dict | None:
        """Candidate: fetch their own score. Open route — no auth header needed."""
        url = f"{self.relay_url}/sessions/{code}/{cid}/score"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (404, 403):
                return None
            raise TransportError(f"GET /sessions/{code}/{cid}/score → {e.code}")
        except Exception as e:
            raise TransportError(f"GET score failed: {e}")


# ─── Factory ──────────────────────────────────────────────────────────────────

def get_transport() -> Transport:
    relay_url = get_relay_url()
    if relay_url:
        return RelayTransport(relay_url, hm_key=get_hm_key(), api_key=get_relay_api_key())
    return EmailTransport()


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Send sealed session via configured transport")
    parser.add_argument("command", choices=["send"])
    parser.add_argument("--code", required=True, help="Interview code to send")
    args = parser.parse_args()

    if args.command == "send":
        transport = get_transport()
        mode = "relay" if get_relay_url() else "email"
        print(f"  Sending via {mode}...")
        transport.send(args.code)


if __name__ == "__main__":
    main()

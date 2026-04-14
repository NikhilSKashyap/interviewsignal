"""
interview.core.transport
------------------------
Transport layer abstraction. Decouples session delivery and retrieval
from the underlying mechanism (email vs. relay).

Config-driven — no code changes needed to switch:
  ~/.interview/config.json:
    relay_url set   → RelayTransport (candidate pushes to relay, dashboard reads from relay)
    relay_url absent → EmailTransport (current behaviour: SMTP send, local file read)

Public surface:
  get_transport()              → returns the right Transport for current config
  transport.send(code)         → candidate: deliver sealed session to HM
  transport.list_sessions()    → HM dashboard: list available sessions
  transport.get_session(code)  → HM dashboard: fetch one session detail
  transport.post_action(...)   → HM dashboard: grade / reveal / comment / decision

All relay calls use stdlib urllib only — no external dependencies.
"""

import base64
import json
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


def is_transport_configured() -> bool:
    """True if either relay or SMTP is configured."""
    config = _load_config()
    has_relay = bool(config.get("relay_url", "").strip())
    has_smtp = bool(config.get("smtp_host", "").strip())
    return has_relay or has_smtp


# ─── Abstract base ────────────────────────────────────────────────────────────

class Transport(ABC):

    @abstractmethod
    def send(self, code: str) -> bool:
        """
        Candidate-side: deliver the sealed session to the HM.
        Returns True on success, False on failure.
        On failure, always print a human-readable message and the local report path
        so the candidate has a manual fallback.
        """

    @abstractmethod
    def list_sessions(self) -> list[dict]:
        """
        HM dashboard: return a list of session summary dicts.
        Each dict must include at minimum: code, submitted_at, elapsed_minutes,
        overall_score (or None), graded (bool), revealed (bool).
        Returns [] on failure — dashboard handles empty state.
        """

    @abstractmethod
    def get_session(self, code: str) -> dict | None:
        """
        HM dashboard: return full session detail dict, or None if not found.
        Must include: manifest, report (report.json contents), grading, comments,
        decision, revealed, audit_entries.
        """

    @abstractmethod
    def post_action(self, code: str, action: str, payload: dict) -> dict:
        """
        HM dashboard: POST a state-changing action.
        action is one of: grade, reveal, comment, decision
        Returns the response dict, or raises TransportError on failure.
        """


class TransportError(Exception):
    """Raised by transport methods when an operation fails unrecoverably."""


# ─── Email transport (current behaviour) ─────────────────────────────────────

class EmailTransport(Transport):
    """
    Original local-first transport.
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

    def get_session(self, code: str) -> dict | None:
        f = RECEIVED_DIR / f"{code}.json"
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text())
        except Exception:
            return None

    def post_action(self, code: str, action: str, payload: dict) -> dict:
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
            return record_decision(
                code,
                payload.get("decision"),
                payload.get("reason", ""),
            )

        raise TransportError(f"Unknown action: {action}")


# ─── Relay transport ──────────────────────────────────────────────────────────

class RelayTransport(Transport):
    """
    Relay-backed transport. Candidate pushes full sealed session to the relay.
    HM dashboard reads from the relay. All HM actions POST to the relay.

    Falls back to EmailTransport.send() if relay submission fails, so
    candidates always have a path to deliver their work.
    """

    def __init__(self, relay_url: str, api_key: str = ""):
        self.relay_url = relay_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
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
                ct = resp.headers.get("Content-Type", "")
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

    def send(self, code: str) -> bool:
        session_dir = SESSIONS_DIR / code

        # Encode all available session files
        payload: dict = {"code": code}
        file_map = {
            "manifest_json": "manifest.json",
            "events_jsonl":  "events.jsonl",
            "report_html":   "report.html",
            "report_json":   "report.json",
        }
        for key, fname in file_map.items():
            f = session_dir / fname
            if f.exists():
                payload[key] = base64.b64encode(f.read_bytes()).decode()

        if "manifest_json" not in payload or "events_jsonl" not in payload:
            print(f"✗ Cannot submit: manifest.json or events.jsonl missing for {code}.")
            return False

        try:
            self._request("POST", "/sessions", body=payload, timeout=60)
            print(f"✓ Session submitted to relay: {self.relay_url}")
            return True
        except TransportError as e:
            print(f"⚠ Relay submission failed: {e}")
            print(f"  Falling back to email...")
            return EmailTransport().send(code)

    def list_sessions(self) -> list[dict]:
        try:
            result = self._request("GET", "/sessions")
            return result if isinstance(result, list) else []
        except TransportError:
            return []

    def get_session(self, code: str) -> dict | None:
        try:
            result = self._request("GET", f"/sessions/{code}")
            return result if isinstance(result, dict) else None
        except TransportError:
            return None

    def post_action(self, code: str, action: str, payload: dict) -> dict:
        try:
            result = self._request("POST", f"/sessions/{code}/{action}", body=payload)
            return result if isinstance(result, dict) else {}
        except TransportError as e:
            raise TransportError(f"Action '{action}' failed: {e}")


# ─── Factory ──────────────────────────────────────────────────────────────────

def get_transport() -> Transport:
    """
    Return the appropriate transport based on config.
    This is the only function callers need — they never instantiate transports directly.
    """
    relay_url = get_relay_url()
    if relay_url:
        return RelayTransport(relay_url, api_key=get_relay_api_key())
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
        success = transport.send(args.code)
        if not success and mode == "email":
            # email_sender already printed instructions
            pass


if __name__ == "__main__":
    main()

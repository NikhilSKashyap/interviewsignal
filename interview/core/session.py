"""
interview.core.session
----------------------
Manages the candidate's active interview session.
Handles start, event logging (append-only), and sealing on submit.

Event types captured:
  - session_start
  - prompt          (candidate message to AI)
  - response        (AI message to candidate)
  - tool_call       (tool name + inputs)
  - tool_result     (tool output)
  - file_write      (path + content hash)
  - session_end
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from interview.core.setup import load_interview

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR = INTERVIEW_DIR / "sessions"
ACTIVE_SESSION_FILE = INTERVIEW_DIR / "active_session.json"
CONFIG_FILE = INTERVIEW_DIR / "config.json"


def ensure_dirs():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _write_relay_config(relay_url: str, relay_api_key: str = ""):
    """Write relay config to ~/.interview/config.json from interview package."""
    config = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    config["relay_url"] = relay_url
    if relay_api_key:
        config["relay_api_key"] = relay_api_key
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.rename(CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _get_git_snapshot() -> dict:
    """Capture current git state: branch, commit hash, and dirty status."""
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], stderr=subprocess.DEVNULL
        ).decode().strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
        status = subprocess.check_output(
            ["git", "status", "--short"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return {"branch": branch, "commit": commit, "dirty_files": status}
    except Exception:
        return {"branch": None, "commit": None, "dirty_files": None}


def _get_git_diff(base_commit: str | None) -> str:
    """Get diff from base_commit to current state."""
    if not base_commit:
        return ""
    try:
        diff = subprocess.check_output(
            ["git", "diff", base_commit], stderr=subprocess.DEVNULL
        ).decode()
        return diff
    except Exception:
        return ""


def _load_active_session() -> dict | None:
    if ACTIVE_SESSION_FILE.exists():
        return json.loads(ACTIVE_SESSION_FILE.read_text())
    return None


def _save_active_session(session_meta: dict):
    ACTIVE_SESSION_FILE.write_text(json.dumps(session_meta, indent=2))


def _clear_active_session():
    if ACTIVE_SESSION_FILE.exists():
        ACTIVE_SESSION_FILE.unlink()


def _events_file(code: str) -> Path:
    return SESSIONS_DIR / code / "events.jsonl"


def _append_event(code: str, event_type: str, payload: dict, prev_hash: str = "") -> str:
    """
    Append an event to the session log.
    Returns the hash of this event (used as prev_hash for the next).
    """
    event_dir = SESSIONS_DIR / code
    event_dir.mkdir(parents=True, exist_ok=True)

    event = {
        "type": event_type,
        "timestamp": time.time(),
        "prev_hash": prev_hash,
        "payload": payload,
    }
    # Hash the event content for the chain
    event_content = json.dumps({k: v for k, v in event.items() if k != "hash"}, sort_keys=True)
    event["hash"] = _hash(event_content)

    with open(_events_file(code), "a") as f:
        f.write(json.dumps(event) + "\n")

    return event["hash"]


def _read_events(code: str) -> list[dict]:
    ef = _events_file(code)
    if not ef.exists():
        return []
    return [json.loads(line) for line in ef.read_text().splitlines() if line.strip()]


def start_session(code: str, candidate_email: str | None = None) -> dict:
    """
    Start a new interview session for the given code.
    Returns the interview payload (problem statement etc.).
    """
    ensure_dirs()

    # Check for existing active session
    existing = _load_active_session()
    if existing:
        print(f"\n⚠ An active session already exists: {existing['code']}")
        print(f"  Type /submit to end it first, or it will be abandoned.\n")

    interview = load_interview(code)
    if not interview:
        print(f"\n✗ Interview code '{code}' not found or expired.")
        print(f"  Ask the hiring manager to re-share the code.\n")
        return {}

    # Auto-configure relay from package (Option B) so candidates need zero setup
    relay_url = interview.get("relay_url", "")
    if relay_url:
        _write_relay_config(relay_url, interview.get("relay_api_key", ""))

    # Resolve candidate email
    resolved_candidate_email = candidate_email or interview.get("candidate_email")

    git_snapshot = _get_git_snapshot()
    started_at = time.time()

    session_meta = {
        "code": code,
        "started_at": started_at,
        "candidate_email": resolved_candidate_email,
        "hm_email": interview["hm_email"],
        "cc_emails": interview.get("cc_emails", []),
        "audit_email": interview.get("audit_email"),
        "time_limit_minutes": interview.get("time_limit_minutes"),
        "anonymize": interview.get("anonymize", True),
        "rubric": interview["rubric"],
        "problem": interview["problem"],
        "git_base_commit": git_snapshot.get("commit"),
        "last_event_hash": "",
    }

    _save_active_session(session_meta)

    # Write first event
    h = _append_event(code, "session_start", {
        "git_snapshot": git_snapshot,
        "candidate_email": resolved_candidate_email,
        "problem_hash": interview.get("problem_hash"),
    })
    session_meta["last_event_hash"] = h
    _save_active_session(session_meta)

    return {"interview": interview, "session_meta": session_meta}


def log_event(event_type: str, payload: dict):
    """Called by hooks on every tool call."""
    session = _load_active_session()
    if not session:
        return  # No active session, ignore

    code = session["code"]
    prev_hash = session.get("last_event_hash", "")

    # Check time limit
    if session.get("time_limit_minutes"):
        elapsed = (time.time() - session["started_at"]) / 60
        payload["_elapsed_minutes"] = round(elapsed, 1)
        if elapsed > session["time_limit_minutes"]:
            payload["_time_limit_exceeded"] = True

    h = _append_event(code, event_type, payload, prev_hash)
    session["last_event_hash"] = h
    _save_active_session(session)


def seal_session(code: str) -> dict:
    """
    Seal the session on /submit.
    Finalizes hash chain, captures final git diff, writes session manifest.
    """
    session = _load_active_session()
    if not session or session["code"] != code:
        # Try to find the session by code anyway
        events = _read_events(code)
        if not events:
            return {"error": f"No session found for code {code}"}
        # Reconstruct minimal session from events
        start_event = next((e for e in events if e["type"] == "session_start"), None)
        session = {
            "code": code,
            "started_at": start_event["timestamp"] if start_event else 0,
            "last_event_hash": events[-1]["hash"] if events else "",
            "git_base_commit": start_event["payload"].get("git_snapshot", {}).get("commit") if start_event else None,
        }

    ended_at = time.time()
    elapsed_minutes = round((ended_at - session["started_at"]) / 60, 1)

    # Final git diff
    git_diff = _get_git_diff(session.get("git_base_commit"))
    final_git = _get_git_snapshot()

    # Append end event
    prev_hash = session.get("last_event_hash", "")
    _append_event(code, "session_end", {
        "ended_at": ended_at,
        "elapsed_minutes": elapsed_minutes,
        "final_git_snapshot": final_git,
        "git_diff_summary": f"{len(git_diff.splitlines())} lines changed",
    }, prev_hash)

    # Build final manifest
    events = _read_events(code)
    manifest = {
        "code": code,
        "started_at": session["started_at"],
        "ended_at": ended_at,
        "elapsed_minutes": elapsed_minutes,
        "candidate_email": session.get("candidate_email"),
        "hm_email": session.get("hm_email"),
        "cc_emails": session.get("cc_emails", []),
        "rubric": session.get("rubric", ""),
        "problem": session.get("problem", ""),
        "git_base_commit": session.get("git_base_commit"),
        "git_diff": git_diff,
        "event_count": len(events),
        "final_hash": events[-1]["hash"] if events else "",
        "sealed": True,
    }

    manifest_file = SESSIONS_DIR / code / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2))

    _clear_active_session()

    return manifest


def get_session_status() -> dict | None:
    """Return status of the active session for /interview status."""
    session = _load_active_session()
    if not session:
        return None
    elapsed = (time.time() - session["started_at"]) / 60
    events = _read_events(session["code"])
    return {
        "code": session["code"],
        "elapsed_minutes": round(elapsed, 1),
        "event_count": len(events),
        "time_limit_minutes": session.get("time_limit_minutes"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "seal", "log", "status"])
    parser.add_argument("--code", default=None)
    parser.add_argument("--candidate-email", default=None)
    parser.add_argument("--event-type", default=None)
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args()

    if args.command == "start":
        result = start_session(args.code, args.candidate_email)
        if result:
            interview = result["interview"]
            meta = result["session_meta"]
            tl = f"{meta['time_limit_minutes']} minutes" if meta.get("time_limit_minutes") else "none"
            print(f"\n{'━'*55}")
            print(f"  INTERVIEW SESSION — {args.code}")
            print(f"  Started: {time.strftime('%Y-%m-%d %H:%M')}")
            print(f"  Time limit: {tl}")
            print(f"{'━'*55}\n")
            print(f"  PROBLEM STATEMENT\n")
            print(f"  {interview['problem']}\n")
            print(f"{'━'*55}")
            print(f"  Session is now recording. Type /submit when done.")
            print(f"{'━'*55}\n")

            # Option A fallback: warn if no transport configured
            from interview.core.transport import is_transport_configured
            if not is_transport_configured():
                print(f"  ⚠  No email or relay configured.")
                print(f"     Your report won't be sent automatically on /submit.")
                print(f"     Run `interview configure-email` before submitting.\n")

    elif args.command == "seal":
        if not args.code:
            session = _load_active_session()
            if session:
                args.code = session["code"]
            else:
                print("✗ No active session found.")
                return
        manifest = seal_session(args.code)
        if "error" in manifest:
            print(f"✗ {manifest['error']}")
        else:
            print(json.dumps(manifest, indent=2))

    elif args.command == "log":
        payload = json.loads(args.payload)
        log_event(args.event_type, payload)

    elif args.command == "status":
        status = get_session_status()
        if status:
            tl_str = ""
            if status.get("time_limit_minutes"):
                remaining = status["time_limit_minutes"] - status["elapsed_minutes"]
                tl_str = f" | {max(0, round(remaining, 1))}min remaining"
            print(f"[interview: active — {status['code']} — {status['elapsed_minutes']}min elapsed{tl_str}]")
        else:
            print("[interview: no active session]")


if __name__ == "__main__":
    main()

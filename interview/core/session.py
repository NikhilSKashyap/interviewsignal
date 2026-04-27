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
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from interview.core.setup import load_interview

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR = INTERVIEW_DIR / "sessions"
ACTIVE_SESSION_FILE = INTERVIEW_DIR / "active_session.json"
CONFIG_FILE = INTERVIEW_DIR / "config.json"


def ensure_dirs():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _write_relay_config(relay_url: str, hm_key: str = "", relay_api_key: str = ""):
    """Write relay config to ~/.interview/config.json from interview package."""
    config = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    config["relay_url"] = relay_url
    if hm_key:
        config["hm_key"] = hm_key
    if relay_api_key:
        config["relay_api_key"] = relay_api_key
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.rename(CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def _chain_hash(prev_hash: str, body: dict) -> str:
    """
    hash[n] = SHA256(prev_hash_bytes || json(body_bytes))
    prev_hash is prepended as raw bytes so the chain dependency is explicit
    and canonical — not embedded as a JSON field (which is weaker).
    body must NOT include "hash" or "prev_hash" keys.
    """
    content = json.dumps(body, sort_keys=True)
    return hashlib.sha256((prev_hash + content).encode()).hexdigest()[:16]


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


def _create_github_repo(github_token: str, code: str) -> str | None:
    """
    Create a public GitHub repo for this interview session via the GitHub API.
    Returns the HTML repo URL on success, None on any failure (non-blocking).
    Tries repo name suffixes on 422 (name conflict).
    """
    base_name = f"interview-{code}"
    for attempt in range(1, 4):
        repo_name = base_name if attempt == 1 else f"{base_name}-{attempt}"
        data = json.dumps({
            "name":        repo_name,
            "private":     False,
            "description": f"interviewsignal session — {code}",
            "auto_init":   False,
        }).encode()
        req = urllib.request.Request(
            "https://api.github.com/user/repos",
            data=data,
            headers={
                "Authorization":        f"Bearer {github_token}",
                "Accept":               "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent":           "interviewsignal",
                "Content-Type":         "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                return result.get("html_url") or None
        except urllib.error.HTTPError as e:
            if e.code == 422:
                continue  # Name conflict — try next suffix
            # Rate limit, API down, etc.
            return None
        except Exception:
            return None
    return None


def _ensure_git_init(code: str):
    """
    Ensure the working directory is a git repo and has an initial session commit.
    Always called at session start — non-blocking.
    """
    cwd = os.getcwd()
    try:
        is_git = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd, capture_output=True,
        ).returncode == 0
        if not is_git:
            subprocess.run(["git", "init"], cwd=cwd, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m",
             f"interview session start — {code}"],
            cwd=cwd, capture_output=True,
        )
    except Exception:
        pass


def _add_github_remote(repo_url: str):
    """Add or update the 'interview' git remote. Non-blocking."""
    cwd = os.getcwd()
    try:
        subprocess.run(
            ["git", "remote", "remove", "interview"],
            cwd=cwd, capture_output=True,
        )
        subprocess.run(
            ["git", "remote", "add", "interview", repo_url],
            cwd=cwd, capture_output=True,
        )
    except Exception:
        pass


def _git_push_session(session_meta: dict) -> bool:
    """
    Stage and commit all session changes, then push to the GitHub remote.
    Uses the stored github_token for authentication.
    Clears the token from the remote URL after push.
    Returns True on success, False on any failure.
    """
    repo_url    = session_meta.get("github_repo_url")
    github_token = session_meta.get("github_token")
    code        = session_meta.get("code", "")

    if not repo_url or not github_token:
        return False

    cwd = os.getcwd()
    try:
        # Commit all session changes
        subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m",
             f"interview session end — {code}"],
            cwd=cwd, capture_output=True,
        )

        # Embed token in remote URL for authenticated push
        token_url = repo_url.replace("https://", f"https://{github_token}@")
        subprocess.run(
            ["git", "remote", "set-url", "interview", token_url],
            cwd=cwd, capture_output=True,
        )

        result = subprocess.run(
            ["git", "push", "--force", "interview", "HEAD:main"],
            cwd=cwd, capture_output=True, timeout=60,
        )

        # Always clear credentials from remote URL
        subprocess.run(
            ["git", "remote", "set-url", "interview", repo_url],
            cwd=cwd, capture_output=True,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode()[:200] if result.stderr else ""
            print(f"  ⚠  Git push failed — your code is still submitted but the repo "
                  f"won't be browsable.\n     {stderr}")
            return False
        return True
    except Exception as e:
        # Ensure credentials are cleared even on exception
        try:
            subprocess.run(
                ["git", "remote", "set-url", "interview", repo_url],
                cwd=cwd, capture_output=True,
            )
        except Exception:
            pass
        print(f"  ⚠  Git push failed: {e}")
        return False


def _load_active_session() -> dict | None:
    if ACTIVE_SESSION_FILE.exists():
        return json.loads(ACTIVE_SESSION_FILE.read_text())
    return None


def _save_active_session(session_meta: dict):
    # Atomic write: concurrent tool calls from Claude Code can race here.
    # Write to .tmp then rename — same pattern used throughout the codebase.
    tmp = ACTIVE_SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(session_meta, indent=2))
    tmp.replace(ACTIVE_SESSION_FILE)


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

    # body is everything except hash and prev_hash — prev_hash is prepended raw
    body = {"type": event_type, "timestamp": time.time(), "payload": payload}
    event = {
        "type": body["type"],
        "timestamp": body["timestamp"],
        "prev_hash": prev_hash,
        "payload": payload,
        "hash": _chain_hash(prev_hash, body),
    }

    with open(_events_file(code), "a") as f:
        f.write(json.dumps(event) + "\n")

    return event["hash"]


def _read_events(code: str) -> list[dict]:
    ef = _events_file(code)
    if not ef.exists():
        return []
    return [json.loads(line) for line in ef.read_text().splitlines() if line.strip()]


def _authenticate_github(relay_url: str, code: str) -> dict | None:
    """
    Run the GitHub OAuth flow via the relay.

    Returns one of:
      {"github_id": ..., "github_username": ..., "avatar_url": ..., "session_token": ...}
                        — success; caller proceeds with GitHub identity
      {"duplicate": True}
                        — already submitted; caller should abort
      {"blocked": True, "reason": str}
                        — OAuth is configured on the relay but could not complete;
                          caller must abort (do not fall back to email-only)
      None              — OAuth not configured on this relay; caller continues with email-only
    """
    start_url = f"{relay_url.rstrip('/')}/auth/github/start?code={code}"
    try:
        req = urllib.request.Request(start_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 501:
            # Relay explicitly says GitHub OAuth is not configured — skip silently
            return None
        # Any other HTTP error: relay is reachable but auth failed. Block.
        return {"blocked": True, "reason": f"Relay returned HTTP {e.code}. Please try again."}
    except Exception as e:
        # Timeout / connection error: relay is in the package so it's expected to be up.
        # We cannot verify identity — block rather than silently fall through.
        return {"blocked": True, "reason": f"Could not reach relay: {e}. Please try again."}

    # Relay responded. Check whether GitHub OAuth is configured.
    if data.get("github_configured") is False:
        return None  # Relay has no GitHub app — continue with email-only
    if not data.get("url"):
        return None  # No auth URL returned — treat as not configured

    auth_url = data.get("url", "")
    state    = data.get("state", "")
    if not auth_url or not state:
        return None

    print(f"\n  GitHub authentication required.")
    print(f"  Opening your browser for GitHub OAuth...")
    print(f"  If the browser doesn't open, visit:\n  {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass  # Non-fatal — URL already printed above

    poll_url = f"{relay_url.rstrip('/')}/auth/github/poll?state={state}"
    print(f"  Waiting for GitHub authentication", end="", flush=True)

    deadline = time.time() + 300  # 5-minute window
    while time.time() < deadline:
        time.sleep(2)
        print(".", end="", flush=True)
        try:
            req = urllib.request.Request(poll_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
        except Exception:
            continue

        status = result.get("status")
        if status == "complete":
            print(f"\n  ✓ Authenticated as @{result['github_username']}\n")
            return result
        if status == "duplicate":
            print(f"\n")
            print(f"  ✗ @{result.get('github_username', 'This account')} has already submitted for {code}.")
            print(f"    Each GitHub account can only submit once per interview.\n")
            return {"duplicate": True}
        if status in ("error", "expired"):
            print(f"\n  ✗ GitHub authentication failed ({status}).\n")
            return {"blocked": True, "reason": f"Authentication {status}. Run /interview {code} to try again."}

    print(f"\n  ✗ Authentication timed out after 5 minutes.\n")
    return {"blocked": True, "reason": f"Authentication timed out. Run /interview {code} to try again."}


def start_session(code: str, candidate_email: str | None = None, candidate_name: str | None = None) -> dict:
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

    # Auto-configure relay from package so candidates need zero setup
    # hm_key scopes the session to this HM on the multi-tenant relay (Model B)
    relay_url = interview.get("relay_url", "")
    if relay_url:
        _write_relay_config(
            relay_url,
            hm_key=interview.get("hm_key", ""),
            relay_api_key=interview.get("relay_api_key", ""),
        )

    # Always ensure a git repo exists in the working directory for diff capture.
    _ensure_git_init(code)

    # GitHub OAuth — one GitHub account = one submission per interview code.
    # Falls back to email-only only when relay confirms OAuth is not configured.
    # If OAuth is configured but fails (network error, timeout), the session is blocked.
    github_auth: dict | None = None
    if relay_url:
        github_auth = _authenticate_github(relay_url, code)
        if github_auth and github_auth.get("duplicate"):
            return {}  # Already submitted — abort cleanly
        if github_auth and github_auth.get("blocked"):
            print(f"\n✗ Session not started: GitHub authentication required but did not complete.")
            print(f"  {github_auth.get('reason', '')}\n")
            return {}  # OAuth configured but failed — do not fall through to email-only

    # Create a GitHub repo and wire up the remote if OAuth succeeded
    github_repo_url: str | None = None
    if github_auth and not github_auth.get("duplicate"):
        github_token_val = github_auth.get("github_token")
        if github_token_val:
            print(f"  Creating interview repository...", end="", flush=True)
            github_repo_url = _create_github_repo(github_token_val, code)
            if github_repo_url:
                print(f" ✓")
                _add_github_remote(github_repo_url)
            else:
                print(f" ⚠  (repo creation failed — session continues)")

    # Resolve candidate identity — GitHub takes priority, fall back to args
    resolved_candidate_email = (
        (github_auth.get("github_email") if github_auth else None)
        or candidate_email
        or interview.get("candidate_email")
    )
    resolved_candidate_name = (
        (github_auth.get("github_name") if github_auth else None)
        or candidate_name
    )

    git_snapshot = _get_git_snapshot()
    started_at = time.time()

    session_meta = {
        "code":               code,
        "started_at":         started_at,
        "candidate_email":    resolved_candidate_email,
        "candidate_name":     resolved_candidate_name,
        "hm_email":           interview.get("hm_email", ""),
        "cc_emails":          interview.get("cc_emails", []),
        "time_limit_minutes": interview.get("time_limit_minutes"),
        "anonymize":          interview.get("anonymize", False),
        # NOTE: rubric intentionally NOT stored — the HM's rubric must never
        # reach the candidate's machine. Relay-side grading loads it from the
        # relay store via get_rubric() which is never exposed to candidates.
        "problem":            interview["problem"],
        "git_base_commit":    git_snapshot.get("commit"),
        "last_event_hash":    "",
        # GitHub identity (None if relay has no GitHub app configured)
        "github_id":          github_auth.get("github_id")       if github_auth else None,
        "github_username":    github_auth.get("github_username") if github_auth else None,
        "github_name":        github_auth.get("github_name")     if github_auth else None,
        "avatar_url":         github_auth.get("avatar_url")      if github_auth else None,
        "session_token":      github_auth.get("session_token")   if github_auth else None,
        # GitHub repo (None if creation failed or OAuth not configured)
        "github_repo_url":    github_repo_url,
        "github_token":       github_auth.get("github_token")    if github_auth else None,
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

    # Push session code to GitHub repo (non-blocking)
    push_ok = False
    if session.get("github_repo_url") and session.get("github_token"):
        push_ok = _git_push_session(session)
        if not push_ok:
            session["github_repo_url"] = None

    # Final git diff
    git_base = session.get("git_base_commit")
    git_diff = _get_git_diff(git_base)
    final_git = _get_git_snapshot()

    git_diff_note = ""
    if not git_base:
        git_diff_note = "no-git-repo"
    elif git_diff == "" and final_git.get("dirty_files"):
        # git diff ran but returned empty despite dirty state — something failed
        git_diff_note = "diff-failed-dirty-tree"
        print("  ⚠  git diff returned empty but working tree is dirty. Diff may be missing.")
    elif git_diff == "":
        git_diff_note = "no-changes"

    # Append end event
    prev_hash = session.get("last_event_hash", "")
    _append_event(code, "session_end", {
        "ended_at": ended_at,
        "elapsed_minutes": elapsed_minutes,
        "final_git_snapshot": final_git,
        "git_diff_summary": f"{len(git_diff.splitlines())} lines changed",
        "git_diff_note": git_diff_note,
    }, prev_hash)

    # Build final manifest
    events = _read_events(code)
    manifest = {
        "code":              code,
        "candidate_name":    session.get("candidate_name"),
        "candidate_email":   session.get("candidate_email"),
        "github_username":   session.get("github_username"),
        "github_repo_url":   session.get("github_repo_url"),
        "github_avatar_url": session.get("avatar_url"),
        "hm_email":          session.get("hm_email"),
        "cc_emails":         session.get("cc_emails", []),
        # NOTE: rubric intentionally NOT included in manifest — the HM's rubric
        # must never reach the candidate's machine. Relay-side grading loads the
        # rubric from the relay store (get_rubric()) which is never exposed
        # to candidates via any public endpoint.
        "problem":           session.get("problem", ""),
        "started_at":        session["started_at"],
        "ended_at":          ended_at,
        "elapsed_minutes":   elapsed_minutes,
        "git_base_commit":   session.get("git_base_commit"),
        "git_diff":          git_diff,
        "event_count":       len(events),
        "final_hash":        events[-1]["hash"] if events else "",
        "sealed":            True,
        # GitHub identity — None if relay has no GitHub app configured
        "github_id":         session.get("github_id"),
        "avatar_url":        session.get("avatar_url"),
        "session_token":     session.get("session_token"),
        # NOTE: github_token intentionally NOT included — credentials stay local
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
    parser.add_argument("--candidate-name", default=None)
    parser.add_argument("--event-type", default=None)
    parser.add_argument("--payload", default="{}")
    args = parser.parse_args()

    if args.command == "start":
        result = start_session(args.code, args.candidate_email, args.candidate_name)
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

            # Inform candidate if no relay was auto-configured from the package
            from interview.core.transport import is_transport_configured
            if not is_transport_configured():
                hm = meta.get("hm_email", "the hiring manager")
                print(f"  ⚠  No relay configured for this interview.")
                print(f"     Your report will be saved locally on /submit.")
                print(f"     You'll be shown the file path and asked to send it to {hm}.\n")

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

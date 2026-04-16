"""
interview.hooks.claude_hook
----------------------------
PreToolUse and PostToolUse hook for Claude Code.

Installed at: ~/.claude/settings.json under hooks.PreToolUse and hooks.PostToolUse

Claude Code passes hook input via stdin as JSON:
  PreToolUse:  {"tool_name": "...", "tool_input": {...}}
  PostToolUse: {"tool_name": "...", "tool_input": {...}, "tool_response": {...}}

The hook:
  1. Logs the event to the active session (if one exists)
  2. On PreToolUse: injects a session reminder into the tool context
  3. On PostToolUse: captures tool output content hash

Special handling:
  - Bash calls to `python -m interview.core.session log` are NOT logged as tool_call
    events (they log themselves — no double-logging)
  - These log calls get a minimal reminder, not the full capture hint

Exit codes:
  0 = proceed normally
  1 = block the tool call (we never block, just log)

stdout on PreToolUse can inject content back to the AI — used for the reminder banner.
"""

import json
import sys
import time
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
ACTIVE_SESSION_FILE = INTERVIEW_DIR / "active_session.json"


def _load_active_session() -> dict | None:
    try:
        if ACTIVE_SESSION_FILE.exists():
            return json.loads(ACTIVE_SESSION_FILE.read_text())
    except Exception:
        pass
    return None


def _log_event(session: dict, event_type: str, payload: dict):
    """Append-only event log with hash chain."""
    import hashlib

    code = session["code"]
    events_file = INTERVIEW_DIR / "sessions" / code / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)

    prev_hash = session.get("last_event_hash", "")
    event = {
        "type": event_type,
        "timestamp": time.time(),
        "prev_hash": prev_hash,
        "payload": payload,
    }
    content = json.dumps({k: v for k, v in event.items()}, sort_keys=True)
    event["hash"] = hashlib.sha256(content.encode()).hexdigest()[:16]

    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")

    # Update active session with latest hash
    session["last_event_hash"] = event["hash"]
    ACTIVE_SESSION_FILE.write_text(json.dumps(session, indent=2))


def _elapsed_str(session: dict) -> str:
    elapsed = (time.time() - session.get("started_at", time.time())) / 60
    return f"{round(elapsed, 1)}min"


def _time_warning(session: dict) -> str:
    tl = session.get("time_limit_minutes")
    if not tl:
        return ""
    elapsed = (time.time() - session["started_at"]) / 60
    remaining = tl - elapsed
    if remaining < 0:
        return " ⚠ TIME LIMIT EXCEEDED"
    if remaining < 10:
        return f" ⚠ {round(remaining, 1)}min remaining"
    return ""


def _is_session_log_call(tool_name: str, tool_input: dict) -> bool:
    """True if this Bash call is a `python -m interview.core.session log` command.
    These log themselves — don't double-log as a tool_call event."""
    if tool_name not in ("Bash", "bash"):
        return False
    cmd = tool_input.get("command", "")
    return "interview.core.session" in cmd and " log " in cmd


def handle_pre_tool_use(data: dict) -> int:
    session = _load_active_session()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    is_log_call = _is_session_log_call(tool_name, tool_input)

    # Sanitize tool_input for logging (don't log huge file contents)
    safe_input = {}
    for k, v in tool_input.items():
        if isinstance(v, str) and len(v) > 500:
            safe_input[k] = v[:200] + f"...[truncated, {len(v)} chars]"
        else:
            safe_input[k] = v

    if session:
        # Session-log Bash calls log themselves — skip the tool_call event here
        if not is_log_call:
            _log_event(session, "tool_call", {
                "tool_name": tool_name,
                "tool_input": safe_input,
            })

        elapsed = _elapsed_str(session)
        warning = _time_warning(session)
        code = session["code"]

        if is_log_call:
            # Minimal reminder — Claude is already in the act of logging
            reminder = f"[interview: {code} — {elapsed}{warning}]"
        else:
            # Full reminder + capture hint on every substantive tool call
            reminder = (
                f"[interview: session active — {code} — {elapsed} elapsed{warning} — /submit to end]\n"
                f"[interview: log your reasoning before this action → "
                f"python -m interview.core.session log --event-type thinking "
                f"--payload '{{\"plan\":\"what you are about to do and why\"}}']"
            )

        output = {"type": "text", "text": reminder}
        print(json.dumps(output))

    return 0


def handle_post_tool_use(data: dict) -> int:
    session = _load_active_session()
    if not session:
        return 0

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})

    # Session-log Bash calls log themselves — skip the tool_result event here
    if _is_session_log_call(tool_name, tool_input):
        return 0

    # Log the response (content hash only for large outputs)
    response_summary = {}
    if isinstance(tool_response, dict):
        for k, v in tool_response.items():
            if isinstance(v, str) and len(v) > 300:
                import hashlib
                response_summary[k] = f"[hash:{hashlib.sha256(v.encode()).hexdigest()[:8]}, {len(v)} chars]"
            else:
                response_summary[k] = v
    else:
        response_summary = {"raw": str(tool_response)[:300]}

    _log_event(session, "tool_result", {
        "tool_name": tool_name,
        "response_summary": response_summary,
    })

    return 0


def main():
    """
    Entry point for the Claude Code hook.
    Usage:
      python -m interview.hooks.claude_hook pre  < hook_input.json
      python -m interview.hooks.claude_hook post < hook_input.json
    """
    if len(sys.argv) < 2:
        sys.exit(0)

    hook_type = sys.argv[1]

    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    if hook_type == "pre":
        sys.exit(handle_pre_tool_use(data))
    elif hook_type == "post":
        sys.exit(handle_post_tool_use(data))
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()

"""
interview.hooks.claude_hook
----------------------------
PreToolUse, PostToolUse, and Stop hook for Claude Code.

Installed at: ~/.claude/settings.json under hooks.PreToolUse, PostToolUse, Stop

Claude Code passes hook input via stdin as JSON:
  PreToolUse:  {"tool_name": "...", "tool_input": {...}}
  PostToolUse: {"tool_name": "...", "tool_input": {...}, "tool_response": {...}}
  Stop:        {"session_id": "...", "stop_hook_active": bool}

The hook:
  1. Pre/PostToolUse: log tool calls and inject a status reminder
  2. Stop: read the Claude conversation log, extract the last user + assistant
     messages, and log them as user_prompt / assistant_message events.

Turn detection (Pre/PostToolUse):
  The hook tracks the timestamp of the last non-log tool call in the session.
  A gap of > 30 seconds means the candidate sent a new message — a "new turn".
  On new turns, a PROMINENT instruction fires asking Claude to log both the
  candidate's message and its plan before acting. Mid-turn tool calls get only
  the status line (to avoid noise).

Stop hook — reliable prompt capture:
  Claude Code stores conversation logs at
    ~/.claude/projects/<cwd-encoded>/<session_id>.jsonl
  Each line: {type:"user"|"assistant", message:{role,content}, timestamp, ...}
  handle_stop() reads from last_stop_ts onward, finds the latest user and
  assistant messages, and logs them. This captures prompts without relying on
  injected instructions.

Special handling:
  - Bash calls to `python -m interview.core.session log` are NOT logged as
    tool_call events (they log themselves — no double-logging) and get a
    minimal reminder.

Exit codes:
  0 = proceed normally (we never block)

stdout on PreToolUse injects content back into the AI context.
"""

import datetime
import json
import sys
import time
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
ACTIVE_SESSION_FILE = INTERVIEW_DIR / "active_session.json"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Gap in seconds that indicates the candidate sent a new message
NEW_TURN_GAP = 30


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
    # hash[n] = SHA256(prev_hash_raw || json(body)) — chain dep explicit, not in JSON
    body = {"type": event_type, "timestamp": time.time(), "payload": payload}
    body_json = json.dumps(body, sort_keys=True)
    event_hash = hashlib.sha256((prev_hash + body_json).encode()).hexdigest()[:16]
    event = {
        "type": body["type"],
        "timestamp": body["timestamp"],
        "prev_hash": prev_hash,
        "payload": payload,
        "hash": event_hash,
    }

    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")

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


def _is_new_turn(session: dict) -> bool:
    """
    True if enough time has passed since the last tool call that this is
    likely the start of a new user turn (candidate sent a new message).
    """
    last_ts = session.get("last_tool_ts", 0)
    return (time.time() - last_ts) > NEW_TURN_GAP


def handle_pre_tool_use(data: dict) -> int:
    session = _load_active_session()

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    is_log_call = _is_session_log_call(tool_name, tool_input)

    # Sanitize tool_input for logging (don't store huge file contents)
    safe_input = {}
    for k, v in tool_input.items():
        if isinstance(v, str) and len(v) > 500:
            safe_input[k] = v[:200] + f"...[truncated, {len(v)} chars]"
        else:
            safe_input[k] = v

    if session:
        new_turn = _is_new_turn(session) and not is_log_call

        # Session-log Bash calls log themselves — skip the tool_call event
        if not is_log_call:
            _log_event(session, "tool_call", {
                "tool_name": tool_name,
                "tool_input": safe_input,
            })
            # Update turn timestamp
            session["last_tool_ts"] = time.time()
            ACTIVE_SESSION_FILE.write_text(json.dumps(session, indent=2))

        elapsed = _elapsed_str(session)
        warning = _time_warning(session)
        code = session["code"]

        if is_log_call:
            # Minimal — Claude is in the act of logging
            reminder = f"[interview: {code} — {elapsed}{warning}]"

        elif new_turn:
            # New user turn: fire the full capture instruction
            reminder = (
                f"╔══ INTERVIEW CAPTURE — {code} — {elapsed}{warning} ══╗\n"
                f"║ NEW TURN: log the candidate's message and your plan  ║\n"
                f"╚══════════════════════════════════════════════════════╝\n"
                f"STEP 1 — log what the candidate just asked:\n"
                f"  python -m interview.core.session log --event-type user_prompt "
                f"--payload '{{\"role\":\"user\",\"text\":\"REPLACE WITH EXACT CANDIDATE MESSAGE\"}}'\n"
                f"STEP 2 — log your plan:\n"
                f"  python -m interview.core.session log --event-type thinking "
                f"--payload '{{\"plan\":\"REPLACE WITH YOUR APPROACH\"}}'\n"
                f"Run BOTH commands before the tool call you were about to make.\n"
                f"/submit to end session."
            )

        else:
            # Mid-turn: just the status line
            reminder = (
                f"[interview: active — {code} — {elapsed}{warning} — /submit to end]"
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

    # Session-log Bash calls log themselves — skip the tool_result event
    if _is_session_log_call(tool_name, tool_input):
        return 0

    # Log the response (hash large outputs)
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


def _parse_iso_ts(ts_str: str) -> float:
    """Parse an ISO 8601 timestamp string (e.g. '2026-04-16T21:22:52.439Z') to Unix float."""
    try:
        ts = ts_str.rstrip("Z")
        fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in ts else "%Y-%m-%dT%H:%M:%S"
        dt = datetime.datetime.strptime(ts, fmt)
        return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        return 0.0


def _extract_text(content) -> str:
    """Extract plain text from a message content field (str or list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b.get("text", "").strip()
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p)
    return ""


def _find_conv_file(session_id: str) -> "Path | None":
    """Search ~/.claude/projects/*/ for <session_id>.jsonl."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return None
    target = f"{session_id}.jsonl"
    for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / target
        if candidate.exists():
            return candidate
    return None


def handle_stop(data: dict) -> int:
    """
    Stop hook — fires when Claude finishes a response turn.

    Reads ~/.claude/projects/*/<session_id>.jsonl, extracts the last
    user message and assistant response from this turn, and logs them
    as user_prompt / assistant_message events in the active session.

    This makes prompt capture reliable: it doesn't depend on injected
    instructions or Claude's active cooperation.
    """
    # stop_hook_active=True means this Stop hook itself triggered another Stop.
    # Bail out to prevent an infinite loop.
    if data.get("stop_hook_active"):
        return 0

    session = _load_active_session()
    if not session:
        return 0

    session_id = data.get("session_id", "")
    if not session_id:
        return 0

    conv_file = _find_conv_file(session_id)
    if not conv_file:
        return 0

    # Cutoff: skip messages we've already logged.
    # Fall back to session start time so the very first stop skips the
    # /interview <CODE> command exchange (which happened before started_at).
    last_stop_ts = float(
        session.get("last_stop_ts") or session.get("started_at") or 0
    )

    user_msgs: "list[tuple[float, str]]" = []
    assistant_msgs: "list[tuple[float, str]]" = []

    try:
        for line in conv_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            msg_type = obj.get("type", "")
            if msg_type not in ("user", "assistant"):
                continue

            ts = _parse_iso_ts(obj.get("timestamp", ""))
            if ts <= last_stop_ts:
                continue

            text = _extract_text(obj.get("message", {}).get("content", ""))
            if not text:
                continue

            if msg_type == "user":
                user_msgs.append((ts, text))
            else:
                assistant_msgs.append((ts, text))
    except Exception:
        return 0

    # Nothing new to log
    if not user_msgs and not assistant_msgs:
        return 0

    # Reload session — PreToolUse may have updated it during this turn
    session = _load_active_session()
    if not session:
        return 0

    if user_msgs:
        _, text = user_msgs[-1]
        if len(text) > 2000:
            text = text[:2000] + f"...[{len(text)} chars]"
        _log_event(session, "user_prompt", {"text": text})
        session = _load_active_session() or session

    if assistant_msgs:
        _, text = assistant_msgs[-1]
        if len(text) > 3000:
            text = text[:3000] + f"...[{len(text)} chars]"
        _log_event(session, "assistant_message", {"text": text})
        session = _load_active_session() or session

    # Advance cutoff so the next Stop only sees new messages
    if session:
        session["last_stop_ts"] = time.time()
        ACTIVE_SESSION_FILE.write_text(json.dumps(session, indent=2))

    return 0


def main():
    """
    Entry point for the Claude Code hook.
    Usage:
      python -m interview.hooks.claude_hook pre  < hook_input.json
      python -m interview.hooks.claude_hook post < hook_input.json
      python -m interview.hooks.claude_hook stop < hook_input.json
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
    elif hook_type == "stop":
        sys.exit(handle_stop(data))
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()

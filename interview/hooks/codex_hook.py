"""
interview.hooks.codex_hook
--------------------------
Lifecycle hooks for Codex.

Installed at: .codex/hooks.json under hooks.UserPromptSubmit, PreToolUse,
PostToolUse, and Stop.

Codex supports Claude-style PascalCase hook names with snake_case payloads:
  UserPromptSubmit: {"prompt": "...", "session_id": "...", "cwd": "..."}
  PreToolUse:       {"tool_name": "...", "tool_input": {...}}
  PostToolUse:      {"tool_name": "...", "tool_input": {...}, "tool_response": {...}}
  Stop:             {"session_id": "...", "cwd": "..."}

Unlike Claude Code, Codex does not expose a stable local conversation JSONL for
the Stop hook to read. Prompt capture therefore happens at UserPromptSubmit,
tool capture happens at Pre/PostToolUse, and Stop performs the per-turn git
commit cross-check.
"""

import hashlib
import json
import subprocess
import sys
import time
import datetime
from pathlib import Path

from interview.core import session as core_session

INTERVIEW_DIR = Path.home() / ".interview"
ACTIVE_SESSION_FILE = INTERVIEW_DIR / "active_session.json"
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def _load_active_session() -> dict | None:
    try:
        if ACTIVE_SESSION_FILE.exists():
            return json.loads(ACTIVE_SESSION_FILE.read_text())
    except Exception:
        pass
    return None


def _save_active_session(session: dict):
    tmp = ACTIVE_SESSION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, indent=2))
    tmp.replace(ACTIVE_SESSION_FILE)


def _log_event(session: dict, event_type: str, payload: dict):
    code = session["code"]
    prev_hash = session.get("last_event_hash", "")
    event_hash = core_session._append_event(code, event_type, payload, prev_hash)
    session["last_event_hash"] = event_hash
    _save_active_session(session)


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
        return " TIME LIMIT EXCEEDED"
    if remaining < 10:
        return f" {round(remaining, 1)}min remaining"
    return ""


def _truncate(value, max_chars: int):
    if isinstance(value, str) and len(value) > max_chars:
        return value[: max_chars // 2] + f"...[truncated, {len(value)} chars]"
    return value


def _safe_mapping(value, max_chars: int) -> dict:
    if not isinstance(value, dict):
        return {"raw": _truncate(str(value), max_chars)}
    safe = {}
    for key, item in value.items():
        if isinstance(item, str):
            safe[key] = _truncate(item, max_chars)
        else:
            safe[key] = item
    return safe


def _field(data: dict, snake_name: str, camel_name: str = ""):
    if snake_name in data:
        return data.get(snake_name)
    if camel_name:
        return data.get(camel_name)
    return None


def _tool_name(data: dict) -> str:
    return _field(data, "tool_name", "toolName") or ""


def _tool_input(data: dict) -> dict:
    value = _field(data, "tool_input", "toolArgs")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            return {"raw": value}
    return value if isinstance(value, dict) else {}


def _tool_response(data: dict):
    return _field(data, "tool_response", "toolResponse") or data.get("result") or {}


def _is_session_log_call(tool_name: str, tool_input: dict) -> bool:
    if tool_name not in ("Bash", "bash", "local_shell", "shell"):
        return False
    cmd = tool_input.get("command") or tool_input.get("cmd") or ""
    return "interview.core.session" in cmd and " log " in cmd



def _last_prompt(session: dict) -> str:
    prompt = session.get("last_user_prompt", "")
    return prompt if isinstance(prompt, str) else ""


def _parse_iso_ts(ts_str: str) -> float:
    try:
        ts = ts_str.rstrip("Z")
        fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in ts else "%Y-%m-%dT%H:%M:%S"
        dt = datetime.datetime.strptime(ts, fmt)
        return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        return 0.0


def _extract_codex_text(content) -> str:
    """Extract plain text from Codex message content blocks."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("input_text", "output_text", "text"):
                text = block.get("text", "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _find_codex_conv_file(session_id: str) -> "Path | None":
    """Search ~/.codex/sessions for the rollout JSONL that matches session_id."""
    if not session_id or not CODEX_SESSIONS_DIR.exists():
        return None
    pattern = f"*{session_id}.jsonl"
    for candidate in CODEX_SESSIONS_DIR.rglob(pattern):
        if candidate.exists():
            return candidate
    return None


def _collect_codex_messages(
    conv_file: Path, last_stop_ts: float
) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
    user_msgs: list[tuple[float, str]] = []
    assistant_msgs: list[tuple[float, str]] = []

    try:
        lines = conv_file.read_text().splitlines()
    except Exception:
        return user_msgs, assistant_msgs

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        ts = _parse_iso_ts(obj.get("timestamp", ""))
        if ts <= last_stop_ts:
            continue

        if obj.get("type") != "response_item":
            continue
        payload = obj.get("payload", {})
        if payload.get("type") != "message":
            continue

        role = payload.get("role", "")
        text = _extract_codex_text(payload.get("content", ""))
        if not text:
            continue
        if role == "user":
            user_msgs.append((ts, text))
        elif role == "assistant":
            assistant_msgs.append((ts, text))

    return user_msgs, assistant_msgs


def _silent_git_commit(user_text: str):
    try:
        subprocess.run(["git", "add", "-A"], timeout=2, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], timeout=2, capture_output=True
        )
        if result.returncode == 0:
            return
        ts = time.strftime("%H:%M:%S")
        snippet = user_text[:120].replace("\n", " ").strip() if user_text else ""
        msg = f"{ts} - {snippet}" if snippet else ts
        subprocess.run(["git", "commit", "-m", msg], timeout=2, capture_output=True)
    except Exception:
        pass


def handle_user_prompt_submit(data: dict) -> int:
    session = _load_active_session()
    if not session:
        return 0

    prompt = data.get("prompt", "")
    if isinstance(prompt, str) and prompt.strip():
        text = prompt.strip()
        if len(text) > 2000:
            text = text[:2000] + f"...[{len(text)} chars]"
        _log_event(session, "user_prompt", {"text": text})
        session = _load_active_session() or session
        session["last_user_prompt"] = text
        session["last_prompt_ts"] = time.time()
        session["last_stop_ts"] = max(
            float(session.get("last_stop_ts") or 0),
            session["last_prompt_ts"],
        )
        _save_active_session(session)

    elapsed = _elapsed_str(session)
    warning = _time_warning(session)
    code = session["code"]
    reminder = (
        f"[interview: {code} - {elapsed}{warning}] "
        "Before substantive work, log your plan with: "
        "python -m interview.core.session log --event-type thinking "
        "--payload '{\"plan\":\"YOUR APPROACH\"}'"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": reminder,
        }
    }))
    return 0


def handle_pre_tool_use(data: dict) -> int:
    session = _load_active_session()
    if not session:
        return 0

    tool_name = _tool_name(data)
    tool_input = _tool_input(data)
    is_log_call = _is_session_log_call(tool_name, tool_input)

    if not is_log_call:
        _log_event(session, "tool_call", {
            "tool_name": tool_name,
            "tool_input": _safe_mapping(tool_input, 500),
            "platform": "codex",
        })
        session = _load_active_session() or session
        session["last_tool_ts"] = time.time()
        _save_active_session(session)

    # Codex's PreToolUse is a guardrail hook — stdout controls approve/block only.
    # Context injection happens via UserPromptSubmit additionalContext instead.
    print(json.dumps({}))
    return 0


def handle_post_tool_use(data: dict) -> int:
    session = _load_active_session()
    if not session:
        return 0

    tool_name = _tool_name(data)
    tool_input = _tool_input(data)
    if _is_session_log_call(tool_name, tool_input):
        return 0

    response = _tool_response(data)
    if isinstance(response, dict):
        summary = {}
        for key, value in response.items():
            if isinstance(value, str) and len(value) > 300:
                digest = hashlib.sha256(value.encode()).hexdigest()[:8]
                summary[key] = f"[hash:{digest}, {len(value)} chars]"
            else:
                summary[key] = value
    else:
        summary = {"raw": str(response)[:300]}

    _log_event(session, "tool_result", {
        "tool_name": tool_name,
        "response_summary": summary,
        "platform": "codex",
    })
    return 0


def handle_stop(data: dict) -> int:
    session = _load_active_session()
    if not session:
        return 0

    session_id = data.get("session_id", "")
    conv_file = _find_codex_conv_file(session_id)
    last_stop_ts = float(session.get("last_stop_ts") or session.get("started_at") or 0)

    user_msgs: list[tuple[float, str]] = []
    assistant_msgs: list[tuple[float, str]] = []
    if conv_file:
        user_msgs, assistant_msgs = _collect_codex_messages(conv_file, last_stop_ts)

    if user_msgs or assistant_msgs:
        session = _load_active_session()
        if not session:
            return 0

    if user_msgs:
        _, text = user_msgs[-1]
        if len(text) > 2000:
            text = text[:2000] + f"...[{len(text)} chars]"
        _log_event(session, "user_prompt", {"text": text})
        session = _load_active_session() or session
        session["last_user_prompt"] = text

    if assistant_msgs:
        _, text = assistant_msgs[-1]
        if len(text) > 3000:
            text = text[:3000] + f"...[{len(text)} chars]"
        _log_event(session, "assistant_message", {"text": text})
        session = _load_active_session() or session

    session["last_stop_ts"] = time.time()
    _save_active_session(session)
    _silent_git_commit(_last_prompt(session))
    return 0


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    hook_type = sys.argv[1]
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)

    if hook_type in ("user_prompt", "UserPromptSubmit"):
        sys.exit(handle_user_prompt_submit(data))
    if hook_type in ("pre", "PreToolUse"):
        sys.exit(handle_pre_tool_use(data))
    if hook_type in ("post", "PostToolUse"):
        sys.exit(handle_post_tool_use(data))
    if hook_type in ("stop", "Stop"):
        sys.exit(handle_stop(data))
    sys.exit(0)


if __name__ == "__main__":
    main()

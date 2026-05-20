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
from pathlib import Path

from interview.core import session as core_session

INTERVIEW_DIR = Path.home() / ".interview"
ACTIVE_SESSION_FILE = INTERVIEW_DIR / "active_session.json"

NEW_TURN_GAP = 30


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


def _is_new_turn(session: dict) -> bool:
    return (time.time() - session.get("last_tool_ts", 0)) > NEW_TURN_GAP


def _last_prompt(session: dict) -> str:
    prompt = session.get("last_user_prompt", "")
    return prompt if isinstance(prompt, str) else ""


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
    new_turn = _is_new_turn(session) and not is_log_call

    if not is_log_call:
        _log_event(session, "tool_call", {
            "tool_name": tool_name,
            "tool_input": _safe_mapping(tool_input, 500),
            "platform": "codex",
        })
        session = _load_active_session() or session
        session["last_tool_ts"] = time.time()
        _save_active_session(session)

    elapsed = _elapsed_str(session)
    warning = _time_warning(session)
    code = session["code"]
    if is_log_call:
        message = f"[interview: {code} - {elapsed}{warning}]"
    elif new_turn:
        message = (
            f"INTERVIEW CAPTURE - {code} - {elapsed}{warning}: "
            "log your plan before acting."
        )
    else:
        message = f"[interview: active - {code} - {elapsed}{warning} - /submit to end]"

    # Codex currently treats PreToolUse as a guardrail hook, not a developer
    # context injection point. systemMessage is the supported low-friction nudge.
    print(json.dumps({"systemMessage": message}))
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

    assistant_text = (
        data.get("assistant_message")
        or data.get("assistantMessage")
        or data.get("response")
        or data.get("output")
    )
    if isinstance(assistant_text, str) and assistant_text.strip():
        text = assistant_text.strip()
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

import json
import sys

from interview import cli
from interview.core import session as core_session
from interview.hooks import codex_hook


def test_install_codex_writes_valid_hooks_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "hooks.json").write_text(json.dumps({
        "PreToolUse": {"command": "old-shape"},
        "hooks": {
            "SessionStart": [{
                "hooks": [{"type": "command", "command": "echo keep"}],
            }],
        },
    }))

    cli._install_codex(verbose=False)

    data = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    assert "PreToolUse" not in data
    assert set(data["hooks"]) == {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "Stop",
    }

    for event_name in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        group = data["hooks"][event_name][0]
        handler = group["hooks"][0]
        assert handler["type"] == "command"
        assert f"{sys.executable} -m interview.hooks.codex_hook" in handler["command"]

    assert data["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert data["hooks"]["PostToolUse"][0]["matcher"] == "*"
    agents_text = (tmp_path / "AGENTS.md").read_text()
    assert "/interview <CODE>" in agents_text
    assert "/submit" in agents_text
    assert "$interview" not in agents_text


def test_codex_hooks_log_prompt_tool_call_and_result(tmp_path, monkeypatch, capsys):
    interview_dir = tmp_path / ".interview"
    sessions_dir = interview_dir / "sessions"
    active_file = interview_dir / "active_session.json"
    interview_dir.mkdir()

    monkeypatch.setattr(codex_hook, "INTERVIEW_DIR", interview_dir)
    monkeypatch.setattr(codex_hook, "ACTIVE_SESSION_FILE", active_file)
    monkeypatch.setattr(core_session, "SESSIONS_DIR", sessions_dir)

    active_file.write_text(json.dumps({
        "code": "INT-CODEX",
        "started_at": 1000.0,
        "last_event_hash": "",
        "time_limit_minutes": 90,
    }))

    assert codex_hook.handle_user_prompt_submit({"prompt": "Build the parser"}) == 0
    user_output = json.loads(capsys.readouterr().out)
    assert user_output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    assert codex_hook.handle_pre_tool_use({
        "tool_name": "local_shell",
        "tool_input": {"command": "pytest", "long": "x" * 600},
    }) == 0
    pre_output = json.loads(capsys.readouterr().out)
    assert pre_output == {}  # approve with no injection; context goes via UserPromptSubmit

    assert codex_hook.handle_post_tool_use({
        "tool_name": "local_shell",
        "tool_input": {"command": "pytest"},
        "tool_response": {"stdout": "ok", "big": "y" * 500},
    }) == 0

    events_file = sessions_dir / "INT-CODEX" / "events.jsonl"
    events = [json.loads(line) for line in events_file.read_text().splitlines()]
    assert [event["type"] for event in events] == [
        "user_prompt",
        "tool_call",
        "tool_result",
    ]
    assert events[1]["payload"]["platform"] == "codex"
    assert "truncated" in events[1]["payload"]["tool_input"]["long"]
    assert events[2]["payload"]["response_summary"]["big"].startswith("[hash:")
    assert events[1]["prev_hash"] == events[0]["hash"]
    assert events[2]["prev_hash"] == events[1]["hash"]


def test_codex_stop_commits_last_prompt(tmp_path, monkeypatch):
    interview_dir = tmp_path / ".interview"
    active_file = interview_dir / "active_session.json"
    interview_dir.mkdir()

    monkeypatch.setattr(codex_hook, "INTERVIEW_DIR", interview_dir)
    monkeypatch.setattr(codex_hook, "ACTIVE_SESSION_FILE", active_file)

    active_file.write_text(json.dumps({
        "code": "INT-CODEX",
        "started_at": 1000.0,
        "last_event_hash": "abc",
        "last_user_prompt": "Implement search",
    }))

    committed = []
    monkeypatch.setattr(codex_hook, "_silent_git_commit", committed.append)

    assert codex_hook.handle_stop({"session_id": "s1"}) == 0
    assert committed == ["Implement search"]

    session = json.loads(active_file.read_text())
    assert session["last_stop_ts"] > 0


def test_uninstall_codex_removes_only_interviewsignal_hooks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hooks_dir = tmp_path / ".codex"
    hooks_dir.mkdir()
    hooks_file = hooks_dir / "hooks.json"
    hooks_file.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [{
                        "type": "command",
                        "command": "python -m interview.hooks.codex_hook pre",
                    }],
                },
                {"hooks": [{"type": "command", "command": "echo keep"}]},
            ],
            "Stop": [
                {
                    "hooks": [{
                        "type": "command",
                        "command": "python -m interview.hooks.codex_hook stop",
                    }],
                },
            ],
        },
    }))

    cli.cmd_uninstall(type("Args", (), {"platform": "codex"})())

    data = json.loads(hooks_file.read_text())
    assert data["hooks"]["PreToolUse"] == [
        {"hooks": [{"type": "command", "command": "echo keep"}]},
    ]
    assert "Stop" not in data["hooks"]

import json
import sys

from interview import cli
from interview.core import session as core_session
from interview.hooks import codex_hook


def test_install_codex_writes_valid_hooks_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(cli.Path, "home", lambda: home)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "hooks.json").write_text(json.dumps({
        "PreToolUse": {"command": "old-shape"},
        "hooks": {
            "SessionStart": [{
                "hooks": [{"type": "command", "command": "echo keep"}],
            }],
        },
    }))
    (home / ".codex").mkdir()
    (home / ".codex" / "hooks.json").write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{
                "matcher": "*",
                "hooks": [{
                    "type": "command",
                    "command": "python -m assignment.hooks.claude_hook pre",
                }],
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
    assert "If stdout is not visible in the chat" in agents_text

    global_agents_text = (home / ".codex" / "AGENTS.md").read_text()
    assert "show the full interview banner and" in global_agents_text
    assert "problem statement from stdout" in global_agents_text
    assert (home / ".agents" / "skills" / "interview" / "SKILL.md").exists()

    global_hooks = json.loads((home / ".codex" / "hooks.json").read_text())
    pre_commands = [
        handler["command"]
        for group in global_hooks["hooks"]["PreToolUse"]
        for handler in group["hooks"]
    ]
    assert "python -m assignment.hooks.claude_hook pre" in pre_commands
    assert any("interview.hooks.codex_hook pre" in cmd for cmd in pre_commands)


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


def test_codex_stop_imports_rollout_messages(tmp_path, monkeypatch):
    interview_dir = tmp_path / ".interview"
    sessions_dir = interview_dir / "sessions"
    active_file = interview_dir / "active_session.json"
    codex_sessions = tmp_path / ".codex" / "sessions"
    rollout_dir = codex_sessions / "2026" / "05" / "20"
    rollout_dir.mkdir(parents=True)
    interview_dir.mkdir()

    monkeypatch.setattr(codex_hook, "INTERVIEW_DIR", interview_dir)
    monkeypatch.setattr(codex_hook, "ACTIVE_SESSION_FILE", active_file)
    monkeypatch.setattr(codex_hook, "CODEX_SESSIONS_DIR", codex_sessions)
    monkeypatch.setattr(core_session, "SESSIONS_DIR", sessions_dir)

    active_file.write_text(json.dumps({
        "code": "INT-CODEX",
        "started_at": 1779308000.0,
        "last_event_hash": "",
    }))
    rollout = rollout_dir / "rollout-2026-05-20T13-01-43-s1.jsonl"
    rollout.write_text("\n".join([
        json.dumps({
            "timestamp": "2026-05-20T20:14:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Build a calculator"}],
            },
        }),
        json.dumps({
            "timestamp": "2026-05-20T20:14:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "I will implement it."}],
            },
        }),
    ]))

    committed = []
    monkeypatch.setattr(codex_hook, "_silent_git_commit", committed.append)

    assert codex_hook.handle_stop({"session_id": "s1"}) == 0

    events_file = sessions_dir / "INT-CODEX" / "events.jsonl"
    events = [json.loads(line) for line in events_file.read_text().splitlines()]
    assert [event["type"] for event in events] == ["user_prompt", "assistant_message"]
    assert events[0]["payload"]["text"] == "Build a calculator"
    assert events[1]["payload"]["text"] == "I will implement it."
    assert committed == ["Build a calculator"]


def test_seal_repairs_sparse_codex_session_from_rollout(tmp_path, monkeypatch):
    interview_dir = tmp_path / ".interview"
    sessions_dir = interview_dir / "sessions"
    active_file = interview_dir / "active_session.json"
    codex_sessions = tmp_path / ".codex" / "sessions"
    rollout_dir = codex_sessions / "2026" / "05" / "20"
    rollout_dir.mkdir(parents=True)
    interview_dir.mkdir()

    monkeypatch.setattr(core_session, "INTERVIEW_DIR", interview_dir)
    monkeypatch.setattr(core_session, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(core_session, "ACTIVE_SESSION_FILE", active_file)
    monkeypatch.setattr(core_session, "CODEX_SESSIONS_DIR", codex_sessions)

    code = "INT-CODEX"
    started_at = 1779308000.0
    start_hash = core_session._append_event(
        code,
        "session_start",
        {"git_snapshot": {"commit": None}, "candidate_email": "c@example.com"},
        "",
        timestamp=started_at,
    )
    active_file.write_text(json.dumps({
        "code": code,
        "started_at": started_at,
        "last_event_hash": start_hash,
        "git_base_commit": None,
        "problem": "build a calculator",
    }))
    (rollout_dir / "rollout-2026-05-20T13-01-43-s1.jsonl").write_text("\n".join([
        json.dumps({
            "timestamp": "2026-05-20T20:13:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "/interview INT-CODEX"}],
            },
        }),
        json.dumps({
            "timestamp": "2026-05-20T20:14:00.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Build a calculator"}],
            },
        }),
        json.dumps({
            "timestamp": "2026-05-20T20:14:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": "{\"cmd\":\"ls\"}",
            },
        }),
        json.dumps({
            "timestamp": "2026-05-20T20:14:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Done."}],
            },
        }),
    ]))

    manifest = core_session.seal_session(code)

    events_file = sessions_dir / code / "events.jsonl"
    events = [json.loads(line) for line in events_file.read_text().splitlines()]
    assert [event["type"] for event in events] == [
        "session_start",
        "user_prompt",
        "tool_call",
        "assistant_message",
        "session_end",
    ]
    assert manifest["codex_repair"]["imported_events"] == 3
    assert manifest["event_count"] == 5


def test_seal_preserves_recovered_interview_remote_url(tmp_path, monkeypatch):
    interview_dir = tmp_path / ".interview"
    sessions_dir = interview_dir / "sessions"
    active_file = interview_dir / "active_session.json"
    interview_dir.mkdir()

    monkeypatch.setattr(core_session, "INTERVIEW_DIR", interview_dir)
    monkeypatch.setattr(core_session, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(core_session, "ACTIVE_SESSION_FILE", active_file)
    monkeypatch.setattr(core_session, "CODEX_SESSIONS_DIR", tmp_path / "no-codex")
    monkeypatch.setattr(
        core_session,
        "_get_interview_remote_url",
        lambda: "https://github.com/example/interview-INT-CODEX",
    )

    code = "INT-CODEX"
    started_at = 1779308000.0
    start_hash = core_session._append_event(
        code,
        "session_start",
        {"git_snapshot": {"commit": None}, "candidate_email": "c@example.com"},
        "",
        timestamp=started_at,
    )
    active_file.write_text(json.dumps({
        "code": code,
        "started_at": started_at,
        "last_event_hash": start_hash,
        "git_base_commit": None,
        "problem": "build a calculator",
    }))

    manifest = core_session.seal_session(code)

    assert manifest["github_repo_url"] == "https://github.com/example/interview-INT-CODEX"
    assert manifest["github_push_ok"] is False


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

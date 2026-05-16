"""
tests/test_grader.py
--------------------
Unit tests for interview.core.grader — transcript builder and config resolution.

These tests DON'T call the actual LLM. They test:
  - build_transcript() formatting
  - _summarise_tool_input / _summarise_tool_result
  - _get_api_key / _get_llm_config resolution
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── build_transcript tests ──────────────────────────────────────────────────

class TestBuildTranscript:
    @pytest.fixture(autouse=True)
    def setup_session(self, tmp_path):
        self.sessions_dir = tmp_path
        self.code = "TEST-GRADE-001"
        self.session_dir = tmp_path / self.code
        self.session_dir.mkdir()
        self.events_file = self.session_dir / "events.jsonl"

    def _write_events(self, events):
        with open(self.events_file, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def _build(self):
        from interview.core import grader
        with patch.object(grader, "SESSIONS_DIR", self.sessions_dir):
            return grader.build_transcript(self.code)

    def test_empty_session(self):
        self._write_events([])
        result = self._build()
        assert result == ""

    def test_no_events_file(self):
        self.events_file.unlink(missing_ok=True)
        result = self._build()
        assert "no session events" in result.lower()

    def test_session_start_format(self):
        self._write_events([{
            "type": "session_start",
            "timestamp": 1000.0,
            "payload": {"git_snapshot": {"branch": "main", "commit": "abc12345"}},
        }])
        result = self._build()
        assert "SESSION START" in result
        assert "abc12345" in result

    def test_user_prompt_format(self):
        self._write_events([
            {"type": "session_start", "timestamp": 1000.0, "payload": {}},
            {"type": "user_prompt", "timestamp": 1120.0, "payload": {"text": "write a rate limiter"}},
        ])
        result = self._build()
        assert "CANDIDATE:" in result
        assert "rate limiter" in result
        assert "T+2.0min" in result

    def test_thinking_format(self):
        self._write_events([
            {"type": "session_start", "timestamp": 1000.0, "payload": {}},
            {"type": "thinking", "timestamp": 1060.0, "payload": {"plan": "I'll use token bucket"}},
        ])
        result = self._build()
        assert "THINKING:" in result
        assert "token bucket" in result

    def test_tool_call_write_format(self):
        self._write_events([
            {"type": "session_start", "timestamp": 1000.0, "payload": {}},
            {"type": "tool_call", "timestamp": 1060.0, "payload": {
                "tool_name": "Write",
                "tool_input": {"file_path": "/app/main.py", "content": "x" * 200},
            }},
        ])
        result = self._build()
        assert "→ Write" in result
        assert "main.py" in result
        assert "200 chars" in result

    def test_tool_call_bash_format(self):
        self._write_events([
            {"type": "session_start", "timestamp": 1000.0, "payload": {}},
            {"type": "tool_call", "timestamp": 1060.0, "payload": {
                "tool_name": "Bash",
                "tool_input": {"command": "python -m pytest"},
            }},
        ])
        result = self._build()
        assert "→ Bash" in result
        assert "pytest" in result

    def test_tool_result_format(self):
        self._write_events([
            {"type": "session_start", "timestamp": 1000.0, "payload": {}},
            {"type": "tool_result", "timestamp": 1060.0, "payload": {
                "tool_name": "Bash",
                "response_summary": {"exit_code": 0},
            }},
        ])
        result = self._build()
        assert "← Bash" in result
        assert "exit=0" in result

    def test_session_end_format(self):
        self._write_events([
            {"type": "session_start", "timestamp": 1000.0, "payload": {}},
            {"type": "session_end", "timestamp": 2800.0, "payload": {"elapsed_minutes": 30}},
        ])
        result = self._build()
        assert "SESSION END" in result
        assert "30" in result

    def test_long_prompt_truncated(self):
        """User prompts > 300 chars should be truncated."""
        self._write_events([
            {"type": "session_start", "timestamp": 1000.0, "payload": {}},
            {"type": "user_prompt", "timestamp": 1060.0, "payload": {"text": "x" * 500}},
        ])
        result = self._build()
        # The x's should be truncated to 300
        candidate_line = [l for l in result.splitlines() if "CANDIDATE:" in l][0]
        # Count x's in that line — should be around 300, not 500
        x_count = candidate_line.count("x")
        assert x_count <= 310  # some slack for formatting


# ─── _summarise_tool_input tests ─────────────────────────────────────────────

class TestSummariseToolInput:
    def _call(self, tool, inp):
        from interview.core.grader import _summarise_tool_input
        return _summarise_tool_input(tool, inp)

    def test_write_shows_path_and_size(self):
        result = self._call("Write", {"file_path": "/app/main.py", "content": "abc"})
        assert "main.py" in result
        assert "3 chars" in result

    def test_edit_shows_path_and_size(self):
        result = self._call("Edit", {"file_path": "/app/main.py", "new_string": "def foo(): pass"})
        assert "main.py" in result

    def test_read_shows_path(self):
        result = self._call("Read", {"file_path": "/app/config.json"})
        assert "config.json" in result

    def test_bash_shows_command(self):
        result = self._call("Bash", {"command": "npm test"})
        assert "npm test" in result

    def test_glob_shows_pattern(self):
        result = self._call("Glob", {"pattern": "**/*.py"})
        assert "*.py" in result


# ─── _get_api_key tests ─────────────────────────────────────────────────────

class TestGetApiKey:
    def _call(self):
        from interview.core.grader import _get_api_key
        return _get_api_key()

    def test_env_var_takes_priority(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"anthropic_api_key": "from-file"}))

        from interview.core import grader
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "from-env"}, clear=False),
            patch.object(grader, "CONFIG_FILE", config),
        ):
            assert self._call() == "from-env"

    def test_config_file_fallback(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"anthropic_api_key": "from-file"}))

        from interview.core import grader
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(grader, "CONFIG_FILE", config),
        ):
            # Remove env var if present
            os.environ.pop("ANTHROPIC_API_KEY", None)
            assert self._call() == "from-file"

    def test_no_key_no_base_url_returns_none(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text("{}")

        from interview.core import grader
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(grader, "CONFIG_FILE", config),
        ):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("ANTHROPIC_BASE_URL", None)
            assert self._call() is None

    def test_custom_base_url_allows_empty_key(self, tmp_path):
        """Enterprise proxy path: base_url set but no key → returns empty string (not None)."""
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"anthropic_base_url": "https://proxy.corp.com"}))

        from interview.core import grader
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(grader, "CONFIG_FILE", config),
        ):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            result = self._call()
            assert result == ""


# ─── _get_llm_config tests ──────────────────────────────────────────────────

class TestGetLlmConfig:
    def _call(self):
        from interview.core.grader import _get_llm_config
        return _get_llm_config()

    def test_defaults(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text("{}")

        from interview.core import grader
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(grader, "CONFIG_FILE", config),
        ):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("ANTHROPIC_BASE_URL", None)
            os.environ.pop("INTERVIEW_GRADING_MODEL", None)
            cfg = self._call()
            assert "api.anthropic.com" in cfg["base_url"]
            assert cfg["api_format"] == "anthropic"

    def test_env_overrides_config(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({
            "anthropic_base_url": "https://file-url.com",
            "grading_model": "file-model",
        }))

        from interview.core import grader
        with (
            patch.dict(os.environ, {
                "ANTHROPIC_BASE_URL": "https://env-url.com",
                "INTERVIEW_GRADING_MODEL": "env-model",
            }, clear=False),
            patch.object(grader, "CONFIG_FILE", config),
        ):
            cfg = self._call()
            assert cfg["base_url"] == "https://env-url.com"
            assert cfg["model"] == "env-model"

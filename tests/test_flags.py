"""
tests/test_flags.py
-------------------
Unit tests for interview.core.flags — session quality and tamper detection.

Each flag detector is a pure function: events in, flags out. No side effects,
no disk, no network — easy to test thoroughly.
"""

import pytest
from interview.core.flags import compute_flags


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _evt(etype, ts=1000.0, payload=None, **kw):
    """Build a minimal event dict."""
    e = {"type": etype, "timestamp": ts, "payload": payload or {}}
    if "timestamp_ms" not in kw and etype in ("user_prompt", "tool_call", "thinking"):
        kw.setdefault("timestamp_ms", ts * 1000)
    e.update(kw)
    return e


def _tool(name, ts=1000.0, **payload_extra):
    payload = {"tool_name": name}
    payload.update(payload_extra)
    return _evt("tool_call", ts=ts, payload=payload, timestamp_ms=ts * 1000)


def _prompt(ts=1000.0, text="do something"):
    return _evt("user_prompt", ts=ts, payload={"text": text}, timestamp_ms=ts * 1000)


def _flag_ids(flags):
    return [f["id"] for f in flags]


# ─── too_fast ────────────────────────────────────────────────────────────────

class TestTooFast:
    def test_no_elapsed_no_flag(self):
        flags = compute_flags([], {})
        assert "too_fast" not in _flag_ids(flags)

    def test_under_10pct_is_red(self):
        manifest = {"elapsed_minutes": 5, "time_limit_minutes": 60}
        flags = compute_flags([], manifest)
        fast = [f for f in flags if f["id"] == "too_fast"]
        assert len(fast) == 1
        assert fast[0]["severity"] == "red"

    def test_under_20pct_is_yellow(self):
        manifest = {"elapsed_minutes": 10, "time_limit_minutes": 60}
        flags = compute_flags([], manifest)
        fast = [f for f in flags if f["id"] == "too_fast"]
        assert len(fast) == 1
        assert fast[0]["severity"] == "yellow"

    def test_normal_time_no_flag(self):
        manifest = {"elapsed_minutes": 45, "time_limit_minutes": 60}
        flags = compute_flags([], manifest)
        assert "too_fast" not in _flag_ids(flags)

    def test_no_time_limit_short_session(self):
        manifest = {"elapsed_minutes": 3}
        flags = compute_flags([], manifest)
        fast = [f for f in flags if f["id"] == "too_fast"]
        assert len(fast) == 1
        assert fast[0]["severity"] == "yellow"

    def test_no_time_limit_normal_session(self):
        manifest = {"elapsed_minutes": 30}
        flags = compute_flags([], manifest)
        assert "too_fast" not in _flag_ids(flags)


# ─── few_interactions ────────────────────────────────────────────────────────

class TestFewInteractions:
    def test_zero_interactions_is_red(self):
        events = [_prompt(), _prompt()]
        flags = compute_flags(events, {})
        fi = [f for f in flags if f["id"] == "few_interactions"]
        assert len(fi) == 1
        assert fi[0]["severity"] == "red"

    def test_two_interactions_is_red(self):
        events = [_tool("Read"), _tool("Write")]
        flags = compute_flags(events, {})
        fi = [f for f in flags if f["id"] == "few_interactions"]
        assert fi[0]["severity"] == "red"

    def test_four_interactions_is_yellow(self):
        events = [_tool("Read", ts=i) for i in range(4)]
        flags = compute_flags(events, {})
        fi = [f for f in flags if f["id"] == "few_interactions"]
        assert len(fi) == 1
        assert fi[0]["severity"] == "yellow"

    def test_five_interactions_no_flag(self):
        events = [_tool("Read", ts=i) for i in range(5)]
        flags = compute_flags(events, {})
        assert "few_interactions" not in _flag_ids(flags)


# ─── no_iteration ────────────────────────────────────────────────────────────

class TestNoIteration:
    def test_few_events_no_flag(self):
        """With <= 3 tool calls, no_iteration should not fire."""
        events = [_tool("Read"), _tool("Write")]
        flags = compute_flags(events, {})
        assert "no_iteration" not in _flag_ids(flags)

    def test_many_writes_no_edit_flags(self):
        """5 writes but no edits or failed bash — no iteration signal."""
        events = [
            _evt("tool_call", ts=i, payload={"tool_name": "Write"})
            for i in range(5)
        ]
        flags = compute_flags(events, {})
        assert "no_iteration" in _flag_ids(flags)

    def test_write_then_edit_same_path_no_flag(self):
        """write + edit to same file = iteration detected."""
        events = [
            _evt("file_write", ts=1, payload={}, path="/a.py"),
            _evt("tool_call", ts=2, payload={"tool_name": "Read"}),
            _evt("tool_call", ts=3, payload={"tool_name": "Read"}),
            _evt("tool_call", ts=4, payload={"tool_name": "Read"}),
            _evt("file_edit", ts=5, payload={}, path="/a.py"),
        ]
        flags = compute_flags(events, {})
        assert "no_iteration" not in _flag_ids(flags)

    def test_failed_bash_then_edit_no_flag(self):
        """Failed bash command followed by file_edit = iteration."""
        events = [
            _evt("bash_command", ts=1, payload={}, exit_code=1),
            _evt("file_edit", ts=2, payload={}),
            _evt("tool_call", ts=3, payload={"tool_name": "Read"}),
            _evt("tool_call", ts=4, payload={"tool_name": "Read"}),
            _evt("tool_call", ts=5, payload={"tool_name": "Read"}),
        ]
        flags = compute_flags(events, {})
        assert "no_iteration" not in _flag_ids(flags)


# ─── uniform_timing ──────────────────────────────────────────────────────────

class TestUniformTiming:
    def test_fewer_than_6_no_flag(self):
        events = [_tool("Read", ts=i * 10) for i in range(4)]
        flags = compute_flags(events, {})
        assert "uniform_timing" not in _flag_ids(flags)

    def test_perfectly_uniform_is_red(self):
        """All gaps exactly equal → CV ≈ 0 → red."""
        events = [_tool("Read", ts=i * 10.0) for i in range(8)]
        flags = compute_flags(events, {})
        ut = [f for f in flags if f["id"] == "uniform_timing"]
        assert len(ut) == 1
        assert ut[0]["severity"] == "red"

    def test_high_variance_no_flag(self):
        """Irregular spacing → no flag."""
        times = [0, 5, 50, 55, 200, 210, 500, 900]
        events = [_tool("Read", ts=t) for t in times]
        flags = compute_flags(events, {})
        assert "uniform_timing" not in _flag_ids(flags)


# ─── no_prompts ──────────────────────────────────────────────────────────────

class TestNoPrompts:
    def test_no_prompt_events_flags(self):
        events = [_tool("Read"), _tool("Write")]
        flags = compute_flags(events, {})
        assert "no_prompts" in _flag_ids(flags)

    def test_has_prompts_no_flag(self):
        events = [_prompt(), _tool("Read")]
        flags = compute_flags(events, {})
        assert "no_prompts" not in _flag_ids(flags)


# ─── hooks_gap ───────────────────────────────────────────────────────────────

class TestHooksGap:
    def test_short_session_no_flag(self):
        """< 5 min → skip gap analysis."""
        manifest = {"elapsed_minutes": 3}
        events = [_evt("tool_call", ts=0), _evt("tool_call", ts=180)]
        flags = compute_flags(events, manifest)
        assert "hooks_gap" not in _flag_ids(flags)

    def test_large_gap_is_red(self):
        """Gap > 50% of elapsed → red."""
        manifest = {"elapsed_minutes": 60}
        # 3 events: 0min, 1min, then nothing until 59min
        events = [
            _evt("tool_call", ts=0, timestamp_ms=0),
            _evt("tool_call", ts=60, timestamp_ms=60_000),
            _evt("tool_call", ts=3540, timestamp_ms=3_540_000),
        ]
        flags = compute_flags(events, manifest)
        hg = [f for f in flags if f["id"] == "hooks_gap"]
        assert len(hg) == 1
        assert hg[0]["severity"] == "red"

    def test_moderate_gap_is_yellow(self):
        """Gap between 33%-50% → yellow."""
        manifest = {"elapsed_minutes": 60}
        # Gap from ts=60s to ts=1560s = 25 min = 41.7% of 60 min → yellow.
        # Last event at ts=2100s keeps the trailing gap (9 min) below the 25-min max.
        events = [
            _evt("tool_call", ts=0, timestamp_ms=0),
            _evt("tool_call", ts=60, timestamp_ms=60_000),
            _evt("tool_call", ts=1560, timestamp_ms=1_560_000),  # 25min gap from prev
            _evt("tool_call", ts=2100, timestamp_ms=2_100_000),  # 9min gap — not the max
        ]
        flags = compute_flags(events, manifest)
        hg = [f for f in flags if f["id"] == "hooks_gap"]
        assert len(hg) == 1
        assert hg[0]["severity"] == "yellow"

    def test_even_events_no_flag(self):
        """Events spread evenly → no gap flag."""
        manifest = {"elapsed_minutes": 60}
        events = [
            _evt("tool_call", ts=i * 600, timestamp_ms=i * 600_000)
            for i in range(7)
        ]
        flags = compute_flags(events, manifest)
        assert "hooks_gap" not in _flag_ids(flags)


# ─── diff_event_mismatch ────────────────────────────────────────────────────

class TestDiffEventMismatch:
    def test_no_diff_data_no_flag(self):
        flags = compute_flags([], {})
        assert "diff_event_mismatch" not in _flag_ids(flags)

    def test_small_diff_no_flag(self):
        manifest = {"git_diff_summary": "30 lines changed"}
        flags = compute_flags([], manifest)
        assert "diff_event_mismatch" not in _flag_ids(flags)

    def test_large_diff_few_writes_is_red(self):
        manifest = {"git_diff_summary": "150 lines changed"}
        events = [_tool("Read")]  # no Write/Edit
        flags = compute_flags(events, manifest)
        dem = [f for f in flags if f["id"] == "diff_event_mismatch"]
        assert len(dem) == 1
        assert dem[0]["severity"] == "red"

    def test_medium_diff_few_writes_is_yellow(self):
        manifest = {"git_diff_summary": "75 lines changed"}
        events = [_tool("Read")]
        flags = compute_flags(events, manifest)
        dem = [f for f in flags if f["id"] == "diff_event_mismatch"]
        assert len(dem) == 1
        assert dem[0]["severity"] == "yellow"

    def test_large_diff_many_writes_no_flag(self):
        manifest = {"git_diff_summary": "200 lines changed"}
        events = [_tool("Write", ts=i) for i in range(5)]
        flags = compute_flags(events, manifest)
        assert "diff_event_mismatch" not in _flag_ids(flags)

    def test_no_changes_note_no_flag(self):
        manifest = {"git_diff_summary": "100 lines changed", "git_diff_note": "no-changes"}
        flags = compute_flags([], manifest)
        assert "diff_event_mismatch" not in _flag_ids(flags)


# ─── prompt_event_ratio ──────────────────────────────────────────────────────

class TestPromptEventRatio:
    def test_few_tool_calls_no_flag(self):
        events = [_tool("Read", ts=i) for i in range(5)]
        flags = compute_flags(events, {})
        assert "prompt_event_ratio" not in _flag_ids(flags)

    def test_many_tool_calls_no_prompts_yellow(self):
        events = [_tool("Read", ts=i) for i in range(12)]
        flags = compute_flags(events, {})
        pr = [f for f in flags if f["id"] == "prompt_event_ratio"]
        assert len(pr) == 1
        assert pr[0]["severity"] == "yellow"

    def test_normal_ratio_no_flag(self):
        events = [_prompt(ts=i * 10) for i in range(5)]
        events += [_tool("Read", ts=i) for i in range(15)]
        flags = compute_flags(events, {})
        assert "prompt_event_ratio" not in _flag_ids(flags)


# ─── commit_event_mismatch ───────────────────────────────────────────────────

class TestCommitEventMismatch:
    def test_no_commits_no_writes_no_flag(self):
        flags = compute_flags([], {})
        assert "commit_event_mismatch" not in _flag_ids(flags)

    def test_commits_but_no_writes_is_red(self):
        """Commits exist but zero Write/Edit tool calls → worked outside AI."""
        manifest = {
            "commit_log": [
                {"message": "10:30:00 — implement rate limiter", "hash": "abc"},
                {"message": "10:35:00 — add tests", "hash": "def"},
            ]
        }
        events = [_tool("Read"), _tool("Read")]
        flags = compute_flags(events, manifest)
        cem = [f for f in flags if f["id"] == "commit_event_mismatch"]
        assert len(cem) == 1
        assert cem[0]["severity"] == "red"

    def test_session_start_commit_only_is_not_flagged(self):
        """Only a 'session start' commit should not flag."""
        manifest = {
            "commit_log": [
                {"message": "session start", "hash": "abc"},
            ]
        }
        flags = compute_flags([], manifest)
        assert "commit_event_mismatch" not in _flag_ids(flags)

    def test_writes_but_no_commits_is_yellow(self):
        """Write/Edit events exist but no commits → stop hook disabled."""
        manifest = {"commit_log": []}
        events = [_tool("Write", ts=i) for i in range(5)]
        flags = compute_flags(events, manifest)
        cem = [f for f in flags if f["id"] == "commit_event_mismatch"]
        assert len(cem) == 1
        assert cem[0]["severity"] == "yellow"

    def test_both_commits_and_writes_no_flag(self):
        """Normal session with both commits and Write events → clean."""
        manifest = {
            "commit_log": [
                {"message": "session start", "hash": "abc"},
                {"message": "10:30:00 — implement", "hash": "def"},
            ]
        }
        events = [_tool("Write", ts=i) for i in range(4)]
        flags = compute_flags(events, manifest)
        assert "commit_event_mismatch" not in _flag_ids(flags)


# ─── compute_flags integration ───────────────────────────────────────────────

class TestComputeFlagsIntegration:
    def test_clean_session_no_flags(self):
        """A healthy session should produce no flags."""
        manifest = {
            "elapsed_minutes": 45,
            "time_limit_minutes": 60,
            "commit_log": [
                {"message": "session start", "hash": "aaa"},
                {"message": "10:30:00 — implement", "hash": "bbb"},
            ],
        }
        # Events need tight, varied spacing to avoid hooks_gap and uniform_timing
        base = 1000.0
        events = (
            [_prompt(ts=base + i * 120) for i in range(8)]
            + [_tool("Read", ts=base + i * 90 + 30) for i in range(10)]
            + [_tool("Write", ts=base + i * 150 + 50) for i in range(5)]
            + [_evt("file_write", ts=base + 100, payload={}, path="/a.py")]
            + [_evt("file_edit", ts=base + 200, payload={}, path="/a.py")]
        )
        flags = compute_flags(events, manifest)
        assert flags == [], f"Expected no flags, got: {[f['id'] for f in flags]}"

    def test_never_raises(self):
        """compute_flags should never raise, even with garbage input."""
        # Empty
        compute_flags([], {})
        # None values
        compute_flags([{"type": None}], {"elapsed_minutes": None})
        # Weird types
        compute_flags([42, "bad", None], {"commit_log": "not a list"})

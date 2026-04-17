"""
tests/test_integrity.py
-----------------------
Integration tests for interview.core.integrity.verify_session().

These tests build real events.jsonl / manifest.json files in a temp directory
and verify that:
  1. A clean session passes verification
  2. A tampered session is detected
  3. A manifest whose final_hash was altered is detected
  4. Missing / empty files are handled gracefully
"""

import hashlib
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _chain_hash(prev_hash: str, body: dict) -> str:
    content = json.dumps(body, sort_keys=True)
    return hashlib.sha256((prev_hash + content).encode()).hexdigest()[:16]


def _append_event(events_file: Path, event_type: str, payload: dict,
                  prev_hash: str = "", ts: float | None = None) -> str:
    if ts is None:
        ts = time.time()
    body = {"type": event_type, "timestamp": ts, "payload": payload}
    h = _chain_hash(prev_hash, body)
    event = {
        "type": body["type"],
        "timestamp": body["timestamp"],
        "prev_hash": prev_hash,
        "payload": payload,
        "hash": h,
    }
    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")
    return h


def _build_session(session_dir: Path, n_events: int = 5,
                   tamper_idx: int | None = None,
                   tamper_field: str = "payload",
                   tamper_value=None,
                   bad_manifest_hash: bool = False) -> str:
    """
    Build a session with n_events tool_call events, bookended by
    session_start and session_end.

    tamper_idx: if set, corrupt that event (0-based in the full list including start/end)
    bad_manifest_hash: write a wrong final_hash in manifest.json
    Returns the expected final_hash (of last event before any tampering).
    """
    events_file = session_dir / "events.jsonl"
    t = 1_000_000.0
    prev = ""

    # session_start
    prev = _append_event(events_file, "session_start",
                         {"git_snapshot": {"branch": "main", "commit": "abc123"}},
                         prev_hash=prev, ts=t)
    t += 1.0

    for i in range(n_events):
        prev = _append_event(events_file, "tool_call",
                             {"tool_name": "Read", "step": i},
                             prev_hash=prev, ts=t)
        t += 1.0

    prev = _append_event(events_file, "session_end",
                         {"elapsed_minutes": 10.0}, prev_hash=prev, ts=t)

    final_hash = prev

    # Optionally tamper
    if tamper_idx is not None:
        lines = events_file.read_text().splitlines()
        ev = json.loads(lines[tamper_idx])
        if tamper_field == "payload":
            ev["payload"]["tampered"] = tamper_value or "evil"
        elif tamper_field == "timestamp":
            ev["timestamp"] = tamper_value or 0.0
        elif tamper_field == "hash":
            ev["hash"] = tamper_value or "0000000000000000"
        lines[tamper_idx] = json.dumps(ev)
        events_file.write_text("\n".join(lines) + "\n")

    # Write manifest
    manifest = {
        "code": session_dir.name,
        "started_at": 1_000_000.0,
        "ended_at": 1_000_000.0 + n_events + 2,
        "elapsed_minutes": 10.0,
        "event_count": n_events + 2,
        "final_hash": "badhash000000000" if bad_manifest_hash else final_hash,
        "sealed": True,
    }
    (session_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return final_hash


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestVerifySessionClean:
    def test_clean_session_passes(self, tmp_path):
        code = "TEST-CLEAN"
        session_dir = tmp_path / code
        session_dir.mkdir()
        _build_session(session_dir)

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["ok"] is True
        assert result["chain_intact"] is True
        assert result["manifest_ok"] is True
        assert result["hash_mismatch_count"] == 0
        assert result["broken_at"] is None
        assert result["event_count"] == 7  # start + 5 tool_calls + end

    def test_session_start_and_end_timestamps(self, tmp_path):
        code = "TEST-TIMESTAMPS"
        session_dir = tmp_path / code
        session_dir.mkdir()
        _build_session(session_dir, n_events=3)

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["session_start"] is not None
        assert result["session_end"] is not None
        assert result["elapsed_minutes"] is not None
        assert result["elapsed_minutes"] > 0


class TestVerifySessionTampered:
    def test_payload_tampering_detected(self, tmp_path):
        code = "TEST-TAMPER-PAYLOAD"
        session_dir = tmp_path / code
        session_dir.mkdir()
        _build_session(session_dir, n_events=5, tamper_idx=2)

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["ok"] is False
        assert result["chain_intact"] is False
        assert result["hash_mismatch_count"] > 0
        assert result["broken_at"] is not None

    def test_timestamp_tampering_detected(self, tmp_path):
        code = "TEST-TAMPER-TS"
        session_dir = tmp_path / code
        session_dir.mkdir()
        _build_session(session_dir, n_events=3, tamper_idx=1,
                       tamper_field="timestamp", tamper_value=9999999.0)

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["chain_intact"] is False

    def test_hash_field_forged_still_breaks_next_event(self, tmp_path):
        """
        Attacker rewrites event[2].hash to match tampered content.
        event[3].prev_hash no longer matches → chain still breaks.
        """
        code = "TEST-TAMPER-HASH"
        session_dir = tmp_path / code
        session_dir.mkdir()
        events_file = session_dir / "events.jsonl"
        _build_session(session_dir, n_events=5)

        lines = events_file.read_text().splitlines()
        ev2 = json.loads(lines[2])
        ev2["payload"]["tampered"] = "evil"
        # Recompute hash to cover the tamper
        body2 = {k: v for k, v in ev2.items() if k not in ("hash", "prev_hash")}
        ev2["hash"] = _chain_hash(ev2["prev_hash"], body2)
        lines[2] = json.dumps(ev2)
        events_file.write_text("\n".join(lines) + "\n")

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        # Chain breaks at event 3 (its prev_hash no longer matches)
        assert result["chain_intact"] is False
        assert result["broken_at"] == 3

    def test_first_event_tampering_breaks_full_chain(self, tmp_path):
        code = "TEST-TAMPER-FIRST"
        session_dir = tmp_path / code
        session_dir.mkdir()
        _build_session(session_dir, n_events=4, tamper_idx=0)

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["chain_intact"] is False
        assert result["broken_at"] == 0


class TestVerifySessionManifest:
    def test_bad_manifest_final_hash_detected(self, tmp_path):
        code = "TEST-BAD-MANIFEST"
        session_dir = tmp_path / code
        session_dir.mkdir()
        _build_session(session_dir, bad_manifest_hash=True)

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["manifest_ok"] is False
        assert result["ok"] is False

    def test_clean_chain_with_no_manifest(self, tmp_path):
        """No manifest.json → chain still verified; manifest_ok stays True."""
        code = "TEST-NO-MANIFEST"
        session_dir = tmp_path / code
        session_dir.mkdir()
        _build_session(session_dir)
        (session_dir / "manifest.json").unlink()

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["chain_intact"] is True
        assert result["manifest_ok"] is True  # no manifest = nothing to contradict


class TestVerifySessionEdgeCases:
    def test_missing_session_returns_ok_false(self, tmp_path):
        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session("DOES-NOT-EXIST")

        assert result["ok"] is False
        assert "not found" in result["details"].lower() or result["event_count"] == 0

    def test_empty_events_file_returns_ok_false(self, tmp_path):
        code = "TEST-EMPTY"
        session_dir = tmp_path / code
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("")

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["ok"] is False
        assert result["event_count"] == 0

    def test_single_event_session_passes(self, tmp_path):
        code = "TEST-SINGLE"
        session_dir = tmp_path / code
        session_dir.mkdir()
        events_file = session_dir / "events.jsonl"
        final = _append_event(events_file, "session_start", {"x": 1})
        manifest = {
            "code": code, "event_count": 1, "final_hash": final,
            "sealed": True, "started_at": time.time(), "ended_at": time.time(),
        }
        (session_dir / "manifest.json").write_text(json.dumps(manifest))

        from interview.core import integrity
        with patch.object(integrity, "SESSIONS_DIR", tmp_path):
            result = integrity.verify_session(code)

        assert result["chain_intact"] is True
        assert result["event_count"] == 1

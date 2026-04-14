"""
interview.relay.store
---------------------
File-based session store for the relay server.

One directory per session under <data_dir>/sessions/<code>/:
  manifest.json    — sealed session metadata
  events.jsonl     — hash-chained event log (from candidate)
  report.html      — pre-generated HTML report
  report.json      — machine-readable report summary
  grading.json     — written when HM grades
  comments.jsonl   — append-only comment log
  decision.json    — hire / next_round / reject
  audit.jsonl      — every state-changing action, hash-chained
  meta.json        — submitted_at, revealed_at, graded_at

All writes are atomic (write temp → rename).
"""

import hashlib
import json
import os
import time
from pathlib import Path


class StoreError(Exception):
    pass


class SessionStore:

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    # ─── helpers ─────────────────────────────────────────────────────────────

    def _session_dir(self, code: str) -> Path:
        return self.sessions_dir / code

    def _write_atomic(self, path: Path, content: str | bytes):
        tmp = path.with_suffix(".tmp")
        if isinstance(content, str):
            tmp.write_text(content)
        else:
            tmp.write_bytes(content)
        tmp.replace(path)

    def _load_json(self, path: Path) -> dict | None:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return None

    def _load_jsonl(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        result = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    result.append(json.loads(line))
                except Exception:
                    pass
        return result

    def _append_jsonl(self, path: Path, obj: dict):
        with open(path, "a") as f:
            f.write(json.dumps(obj) + "\n")

    def _hash_chain(self, prev_hash: str, obj: dict) -> str:
        content = prev_hash + json.dumps(obj, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _last_audit_hash(self, code: str) -> str:
        entries = self._load_jsonl(self._session_dir(code) / "audit.jsonl")
        return entries[-1]["hash"] if entries else "0" * 16

    # ─── meta ─────────────────────────────────────────────────────────────────

    def _load_meta(self, code: str) -> dict:
        return self._load_json(self._session_dir(code) / "meta.json") or {}

    def _save_meta(self, code: str, updates: dict):
        meta = self._load_meta(code)
        meta.update(updates)
        self._write_atomic(
            self._session_dir(code) / "meta.json",
            json.dumps(meta, indent=2),
        )

    # ─── audit ────────────────────────────────────────────────────────────────

    def append_audit(self, code: str, event_type: str, extra: dict | None = None):
        prev_hash = self._last_audit_hash(code)
        entry = {
            "type": event_type,
            "code": code,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prev_hash": prev_hash,
            **(extra or {}),
        }
        entry["hash"] = self._hash_chain(prev_hash, entry)
        self._append_jsonl(self._session_dir(code) / "audit.jsonl", entry)
        return entry

    # ─── submit ───────────────────────────────────────────────────────────────

    def exists(self, code: str) -> bool:
        return (self._session_dir(code) / "meta.json").exists()

    def save_session(self, code: str, files: dict[str, bytes]):
        """
        files: dict of filename → raw bytes (manifest.json, events.jsonl, etc.)
        """
        d = self._session_dir(code)
        d.mkdir(parents=True, exist_ok=True)

        for fname, content in files.items():
            self._write_atomic(d / fname, content)

        self._save_meta(code, {
            "code": code,
            "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "graded": False,
            "revealed": False,
        })
        self.append_audit(code, "session_submitted")

    # ─── list / fetch ─────────────────────────────────────────────────────────

    def list_sessions(self) -> list[dict]:
        sessions = []
        for d in sorted(self.sessions_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            meta = self._load_json(d / "meta.json")
            if not meta:
                continue
            report = self._load_json(d / "report.json") or {}
            sessions.append({
                "code":             meta.get("code", d.name),
                "submitted_at":     meta.get("submitted_at"),
                "elapsed_minutes":  report.get("elapsed_minutes"),
                "overall_score":    report.get("overall_score"),
                "graded":           meta.get("graded", False),
                "revealed":         meta.get("revealed", False),
            })
        return sessions

    def get_session(self, code: str) -> dict | None:
        d = self._session_dir(code)
        meta = self._load_json(d / "meta.json")
        if not meta:
            return None
        manifest  = self._load_json(d / "manifest.json") or {}
        report    = self._load_json(d / "report.json") or {}
        grading   = self._load_json(d / "grading.json")
        comments  = self._load_jsonl(d / "comments.jsonl")
        decision  = self._load_json(d / "decision.json")
        audit     = self._load_jsonl(d / "audit.jsonl")
        return {
            "code":          code,
            "submitted_at":  meta.get("submitted_at"),
            "revealed":      meta.get("revealed", False),
            "graded_at":     meta.get("graded_at"),
            "revealed_at":   meta.get("revealed_at"),
            "manifest":      manifest,
            "report":        report,
            "grading":       grading,
            "comments":      comments,
            "decision":      decision,
            "audit_entries": audit,
        }

    def get_file(self, code: str, filename: str) -> bytes | None:
        f = self._session_dir(code) / filename
        return f.read_bytes() if f.exists() else None

    # ─── HM actions ───────────────────────────────────────────────────────────

    def is_graded(self, code: str) -> bool:
        return self._load_meta(code).get("graded", False)

    def save_grade(self, code: str, grading: dict) -> dict:
        if self.is_graded(code):
            raise StoreError("already_graded")
        d = self._session_dir(code)
        graded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        grading["graded_at"] = graded_at
        self._write_atomic(d / "grading.json", json.dumps(grading, indent=2))
        self._save_meta(code, {"graded": True, "graded_at": graded_at})
        self.append_audit(code, "grade_recorded", {
            "overall_score": grading.get("overall_score"),
        })
        return {"code": code, "graded_at": graded_at}

    def record_reveal(self, code: str) -> dict:
        if not self.is_graded(code):
            raise StoreError("not_graded")
        meta = self._load_meta(code)
        graded_at   = meta.get("graded_at", "")
        revealed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Compute human-readable delta
        delta = ""
        if graded_at:
            try:
                import datetime
                fmt = "%Y-%m-%dT%H:%M:%SZ"
                diff = (
                    datetime.datetime.strptime(revealed_at, fmt) -
                    datetime.datetime.strptime(graded_at, fmt)
                ).total_seconds() / 60
                delta = f"{round(diff, 1)} minutes after grade was recorded"
            except Exception:
                pass

        self._save_meta(code, {"revealed": True, "revealed_at": revealed_at})
        self.append_audit(code, "identity_revealed", {"delta": delta})
        return {"code": code, "revealed_at": revealed_at, "delta": delta}

    def add_comment(self, code: str, text: str) -> dict:
        entries = self._load_jsonl(self._session_dir(code) / "comments.jsonl")
        comment = {
            "id":         f"c{len(entries) + 1}",
            "text":       text,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._append_jsonl(self._session_dir(code) / "comments.jsonl", comment)
        self.append_audit(code, "comment_added", {"preview": text[:60]})
        return comment

    def save_decision(self, code: str, decision: str, reason: str = "") -> dict:
        if self._load_json(self._session_dir(code) / "decision.json"):
            raise StoreError("already_decided")
        recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        obj = {"decision": decision, "reason": reason, "recorded_at": recorded_at}
        self._write_atomic(
            self._session_dir(code) / "decision.json",
            json.dumps(obj, indent=2),
        )
        self.append_audit(code, "decision_recorded", {
            "decision": decision,
        })
        return {"code": code, "decision": decision, "recorded_at": recorded_at}

    # ─── audit verification ───────────────────────────────────────────────────

    def verify_all_chains(self) -> dict:
        """Walk every session's audit.jsonl and verify hash chains."""
        broken = []
        total  = 0
        for d in self.sessions_dir.iterdir():
            if not d.is_dir():
                continue
            entries = self._load_jsonl(d / "audit.jsonl")
            prev = "0" * 16
            for i, entry in enumerate(entries):
                total += 1
                stored_hash = entry.get("hash", "")
                check_entry = {k: v for k, v in entry.items() if k != "hash"}
                expected = self._hash_chain(prev, check_entry)
                if stored_hash != expected:
                    broken.append(f"{d.name} entry {i}: expected {expected}, got {stored_hash}")
                prev = stored_hash
        if broken:
            return {"ok": False, "entries": total, "message": f"Hash mismatch: {broken[0]}"}
        return {"ok": True, "entries": total, "message": "Chain intact."}

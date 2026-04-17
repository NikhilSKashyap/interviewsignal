"""
interview.relay.store
---------------------
Multi-tenant file-based store for the relay server.

Layout under <data_dir>:
  code_index.json              — {code: hm_key} global lookup
  hms/
    <hm_key>/
      info.json
      interviews/
        <code>.json            — full interview payload (problem, rubric, etc.)
      sessions/
        <code>/
          <cid>/               — cid = sha256(candidate_email)[:12]
            manifest.json, events.jsonl, report.html, report.json
            grading.json, comments.jsonl, decision.json
            audit.jsonl, meta.json

All writes are atomic (write .tmp → rename).
Single-process assumption: HTTPServer is single-threaded; no file locking needed.
"""

import hashlib
import json
import time
import uuid
from pathlib import Path


class StoreError(Exception):
    pass


def make_cid(email: str) -> str:
    """Deterministic, URL-safe, anonymous candidate ID from email."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()[:12]


def make_github_cid(github_id: int | str) -> str:
    """Deterministic, anonymous candidate ID from GitHub user ID."""
    return hashlib.sha256(f"github:{github_id}".encode()).hexdigest()[:12]


class SessionStore:

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.hms_dir = data_dir / "hms"
        self.hms_dir.mkdir(parents=True, exist_ok=True)

    # ─── path helpers ─────────────────────────────────────────────────────────

    def _hm_dir(self, hm_key: str) -> Path:
        return self.hms_dir / hm_key

    def _interviews_dir(self, hm_key: str) -> Path:
        return self._hm_dir(hm_key) / "interviews"

    def _sessions_dir(self, hm_key: str) -> Path:
        return self._hm_dir(hm_key) / "sessions"

    def _session_dir(self, hm_key: str, code: str, cid: str) -> Path:
        return self._sessions_dir(hm_key) / code / cid

    def _code_index_path(self) -> Path:
        return self.data_dir / "code_index.json"

    # ─── low-level helpers ────────────────────────────────────────────────────

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

    # ─── code index ───────────────────────────────────────────────────────────

    def _load_code_index(self) -> dict:
        return self._load_json(self._code_index_path()) or {}

    def _save_code_index(self, index: dict):
        self._write_atomic(self._code_index_path(), json.dumps(index, indent=2))

    def lookup_hm_for_code(self, code: str) -> str | None:
        return self._load_code_index().get(code)

    # ─── HM registration ──────────────────────────────────────────────────────

    def hm_exists(self, hm_key: str) -> bool:
        return (self._hm_dir(hm_key) / "info.json").exists()

    def register_hm(self) -> str:
        hm_key = str(uuid.uuid4())
        hm_dir = self._hm_dir(hm_key)
        hm_dir.mkdir(parents=True, exist_ok=True)
        (hm_dir / "interviews").mkdir(exist_ok=True)
        (hm_dir / "sessions").mkdir(exist_ok=True)
        registered_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_atomic(
            hm_dir / "info.json",
            json.dumps({"hm_key": hm_key, "registered_at": registered_at}, indent=2),
        )
        return hm_key

    # ─── interviews ───────────────────────────────────────────────────────────

    def register_interview(self, hm_key: str, code: str, payload: dict):
        """Store an interview package and register the code → hm_key mapping."""
        index = self._load_code_index()
        if code in index:
            raise StoreError("already_exists")
        d = self._interviews_dir(hm_key)
        d.mkdir(parents=True, exist_ok=True)
        self._write_atomic(d / f"{code}.json", json.dumps(payload, indent=2))
        index[code] = hm_key
        self._save_code_index(index)

    def get_interview(self, code: str) -> dict | None:
        """Fetch an interview package by code (public — no hm_key needed)."""
        hm_key = self.lookup_hm_for_code(code)
        if not hm_key:
            return None
        return self._load_json(self._interviews_dir(hm_key) / f"{code}.json")

    def list_interviews(self, hm_key: str) -> list[dict]:
        """List all interviews for an HM with candidate submission counts."""
        interviews_dir = self._interviews_dir(hm_key)
        sessions_dir = self._sessions_dir(hm_key)
        if not interviews_dir.exists():
            return []
        result = []
        for f in sorted(interviews_dir.glob("*.json"), reverse=True):
            payload = self._load_json(f)
            if not payload:
                continue
            code = f.stem
            candidates = self._summarise_candidates(hm_key, code)
            problem = payload.get("problem", "")
            first_line = problem.split("\n")[0].strip()
            title = payload.get("title") or (first_line[:60] + ("..." if len(first_line) > 60 else ""))
            result.append({
                "code": code,
                "title": title,
                "created_at": payload.get("created_at"),
                "time_limit_minutes": payload.get("time_limit_minutes"),
                "candidate_count": len(candidates),
                "candidates": candidates,
            })
        return result

    def _summarise_candidates(self, hm_key: str, code: str) -> list[dict]:
        code_dir = self._sessions_dir(hm_key) / code
        result = []
        if not code_dir.exists():
            return result
        for cid_dir in code_dir.iterdir():
            if not cid_dir.is_dir():
                continue
            meta = self._load_json(cid_dir / "meta.json")
            if not meta:
                continue
            report   = self._load_json(cid_dir / "report.json") or {}
            grading  = self._load_json(cid_dir / "grading.json") or {}
            manifest = self._load_json(cid_dir / "manifest.json") or {}
            result.append({
                "cid":             cid_dir.name,
                "submitted_at":    meta.get("submitted_at"),
                "elapsed_minutes": report.get("elapsed_minutes"),
                # Grading result takes precedence over the pre-grading report stub
                "overall_score":   grading.get("overall_score") or report.get("overall_score"),
                "event_count":     manifest.get("event_count"),
                "graded":          meta.get("graded", False),
                "revealed":        meta.get("revealed", False),
            })
        return sorted(result, key=lambda x: x.get("submitted_at") or "", reverse=True)

    # ─── meta ─────────────────────────────────────────────────────────────────

    def _load_meta(self, hm_key: str, code: str, cid: str) -> dict:
        return self._load_json(self._session_dir(hm_key, code, cid) / "meta.json") or {}

    def _save_meta(self, hm_key: str, code: str, cid: str, updates: dict):
        meta = self._load_meta(hm_key, code, cid)
        meta.update(updates)
        self._write_atomic(
            self._session_dir(hm_key, code, cid) / "meta.json",
            json.dumps(meta, indent=2),
        )

    # ─── audit ────────────────────────────────────────────────────────────────

    def _last_audit_hash(self, hm_key: str, code: str, cid: str) -> str:
        entries = self._load_jsonl(self._session_dir(hm_key, code, cid) / "audit.jsonl")
        return entries[-1]["hash"] if entries else "0" * 16

    def append_audit(self, hm_key: str, code: str, cid: str, event_type: str, extra: dict | None = None):
        prev_hash = self._last_audit_hash(hm_key, code, cid)
        entry = {
            "type":      event_type,
            "code":      code,
            "cid":       cid,
            "ts":        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prev_hash": prev_hash,
            **(extra or {}),
        }
        entry["hash"] = self._hash_chain(prev_hash, entry)
        self._append_jsonl(self._session_dir(hm_key, code, cid) / "audit.jsonl", entry)
        return entry

    # ─── sessions ─────────────────────────────────────────────────────────────

    def session_exists(self, hm_key: str, code: str, cid: str) -> bool:
        return (self._session_dir(hm_key, code, cid) / "meta.json").exists()

    MAX_SESSION_BYTES = 100 * 1024 * 1024  # 100 MB per session
    MAX_FILE_BYTES    = 20  * 1024 * 1024  # 20 MB per individual file

    def save_session(self, hm_key: str, code: str, cid: str, candidate_email: str, files: dict[str, bytes], github_identity: dict | None = None):
        # Enforce per-file and per-session size limits
        total = sum(len(v) for v in files.values())
        if total > self.MAX_SESSION_BYTES:
            raise StoreError(f"Session payload too large: {total // 1024 // 1024}MB (limit 100MB)")
        for fname, content in files.items():
            if len(content) > self.MAX_FILE_BYTES:
                raise StoreError(f"File {fname!r} too large: {len(content) // 1024 // 1024}MB (limit 20MB)")

        d = self._session_dir(hm_key, code, cid)
        d.mkdir(parents=True, exist_ok=True)
        for fname, content in files.items():
            self._write_atomic(d / fname, content)
        submitted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Extract elapsed_minutes from manifest if available
        elapsed = None
        if "manifest.json" in files:
            try:
                manifest = json.loads(files["manifest.json"])
                elapsed = manifest.get("elapsed_minutes")
            except Exception:
                pass
        meta: dict = {
            "code":            code,
            "cid":             cid,
            "candidate_email": candidate_email,
            "submitted_at":    submitted_at,
            "elapsed_minutes": elapsed,
            "graded":          False,
            "revealed":        False,
        }
        if github_identity:
            meta["github_id"]       = github_identity.get("github_id")
            meta["github_username"] = github_identity.get("github_username")
            meta["avatar_url"]      = github_identity.get("avatar_url")
            self.record_github_submission(code, github_identity["github_id"], cid)
        self._save_meta(hm_key, code, cid, meta)
        self.append_audit(hm_key, code, cid, "session_submitted")

    def get_session(self, hm_key: str, code: str, cid: str) -> dict | None:
        d = self._session_dir(hm_key, code, cid)
        meta = self._load_json(d / "meta.json")
        if not meta:
            return None
        manifest = self._load_json(d / "manifest.json") or {}
        report   = self._load_json(d / "report.json") or {}
        grading  = self._load_json(d / "grading.json")
        comments = self._load_jsonl(d / "comments.jsonl")
        decision = self._load_json(d / "decision.json")
        audit    = self._load_jsonl(d / "audit.jsonl")
        revealed = meta.get("revealed", False)
        return {
            "code":            code,
            "cid":             cid,
            "submitted_at":    meta.get("submitted_at"),
            "revealed":        revealed,
            "graded_at":       meta.get("graded_at"),
            "revealed_at":     meta.get("revealed_at"),
            "elapsed_minutes": meta.get("elapsed_minutes"),
            "candidate_email": meta.get("candidate_email") if revealed else None,
            "manifest":        manifest,
            "report":          report,
            "grading":         grading,
            "comments":        comments,
            "decision":        decision,
            "audit_entries":   audit,
        }

    # Files the relay is allowed to serve — anything else is rejected to prevent
    # path traversal attacks (e.g. ../../hms/OTHER_KEY/interviews/code.json).
    _ALLOWED_FILES = frozenset({
        "manifest.json",
        "events.jsonl",
        "report.html",
        "report.json",
        "grading.json",
        "debrief.txt",
    })

    def get_file(self, hm_key: str, code: str, cid: str, filename: str) -> bytes | None:
        if filename not in self._ALLOWED_FILES:
            raise StoreError(f"File not allowed: {filename!r}")
        f = self._session_dir(hm_key, code, cid) / filename
        return f.read_bytes() if f.exists() else None

    # ─── HM actions ───────────────────────────────────────────────────────────

    def is_graded(self, hm_key: str, code: str, cid: str) -> bool:
        return self._load_meta(hm_key, code, cid).get("graded", False)

    def save_grade(self, hm_key: str, code: str, cid: str, grading: dict) -> dict:
        if self.is_graded(hm_key, code, cid):
            raise StoreError("already_graded")
        d = self._session_dir(hm_key, code, cid)
        graded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        grading["graded_at"] = graded_at
        self._write_atomic(d / "grading.json", json.dumps(grading, indent=2))
        self._save_meta(hm_key, code, cid, {"graded": True, "graded_at": graded_at})
        self.append_audit(hm_key, code, cid, "grade_recorded",
                          {"overall_score": grading.get("overall_score")})
        return {"code": code, "cid": cid, "graded_at": graded_at}

    def record_reveal(self, hm_key: str, code: str, cid: str) -> dict:
        if not self.is_graded(hm_key, code, cid):
            raise StoreError("not_graded")
        meta = self._load_meta(hm_key, code, cid)
        graded_at   = meta.get("graded_at", "")
        revealed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
        candidate_email = meta.get("candidate_email", "")
        self._save_meta(hm_key, code, cid, {"revealed": True, "revealed_at": revealed_at})
        self.append_audit(hm_key, code, cid, "identity_revealed", {"delta": delta})
        return {
            "code":             code,
            "cid":              cid,
            "revealed_at":      revealed_at,
            "delta":            delta,
            "candidate_email":  candidate_email,
            "github_username":  meta.get("github_username"),
            "avatar_url":       meta.get("avatar_url"),
        }

    def add_comment(self, hm_key: str, code: str, cid: str, text: str) -> dict:
        path = self._session_dir(hm_key, code, cid) / "comments.jsonl"
        entries = self._load_jsonl(path)
        comment = {
            "id":         f"c{len(entries) + 1}",
            "text":       text,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._append_jsonl(path, comment)
        self.append_audit(hm_key, code, cid, "comment_added", {"preview": text[:60]})
        return comment

    def save_decision(self, hm_key: str, code: str, cid: str, decision: str, reason: str = "") -> dict:
        d = self._session_dir(hm_key, code, cid)
        if self._load_json(d / "decision.json"):
            raise StoreError("already_decided")
        recorded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        obj = {"decision": decision, "reason": reason, "recorded_at": recorded_at}
        self._write_atomic(d / "decision.json", json.dumps(obj, indent=2))
        self.append_audit(hm_key, code, cid, "decision_recorded", {"decision": decision})
        return {"code": code, "cid": cid, "decision": decision, "recorded_at": recorded_at}

    # ─── sharing config ───────────────────────────────────────────────────────

    def _sharing_override_path(self, hm_key: str, code: str) -> Path:
        """HM can override the interview's default sharing config per code."""
        return self._hm_dir(hm_key) / "sharing" / f"{code}.json"

    def get_sharing_config(self, hm_key: str, code: str) -> dict:
        """
        Returns the effective sharing config for this code.
        Override file (set via dashboard) takes precedence over interview payload default.
        """
        override_path = self._sharing_override_path(hm_key, code)
        if override_path.exists():
            cfg = self._load_json(override_path)
            if cfg:
                return cfg
        # Fall back to interview payload default
        interview = self._load_json(self._interviews_dir(hm_key) / f"{code}.json")
        if interview:
            sharing = interview.get("sharing")
            if sharing and isinstance(sharing, dict):
                return sharing
        return {"score": "none", "debrief": False, "hm_notes": False}

    def save_sharing_config(self, hm_key: str, code: str, config: dict) -> dict:
        """Persist an HM sharing override for this code. Audit-logged globally."""
        override_path = self._sharing_override_path(hm_key, code)
        override_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(override_path, json.dumps(config, indent=2))
        # Append to a per-code sharing audit log (not per-cid)
        audit_path = self._hm_dir(hm_key) / "sharing" / f"{code}_audit.jsonl"
        entries = self._load_jsonl(audit_path)
        prev_hash = entries[-1]["hash"] if entries else "0" * 16
        entry = {
            "type":      "sharing_updated",
            "code":      code,
            "ts":        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "config":    config,
            "prev_hash": prev_hash,
        }
        entry["hash"] = self._hash_chain(prev_hash, entry)
        self._append_jsonl(audit_path, entry)
        return config

    def get_score_response(self, hm_key: str, code: str, cid: str) -> dict | None:
        """
        Build the public score response for a candidate, filtered by sharing config.
        Returns None if sharing.score == "none" or the session is not yet graded.
        """
        if not self.session_exists(hm_key, code, cid):
            return None
        sharing = self.get_sharing_config(hm_key, code)
        score_level = sharing.get("score", "none")
        if score_level == "none":
            return {"available": False, "reason": "Score sharing is not enabled for this interview."}
        grading = self._load_json(self._session_dir(hm_key, code, cid) / "grading.json")
        if not grading or grading.get("overall_score") is None:
            return {"available": False, "reason": "Your session has not been graded yet."}

        result: dict = {"available": True}
        if score_level in ("overall", "breakdown", "breakdown_notes"):
            result["overall_score"] = grading.get("overall_score")
        if score_level in ("breakdown", "breakdown_notes"):
            result["dimensions"] = grading.get("dimensions", [])
        if score_level == "breakdown_notes":
            result["summary"]          = grading.get("summary", "")
            result["standout_moments"] = grading.get("standout_moments", [])
            result["concerns"]         = grading.get("concerns", [])
            if sharing.get("debrief"):
                debrief_bytes = self.get_file(hm_key, code, cid, "debrief.txt")
                if debrief_bytes:
                    result["debrief"] = debrief_bytes.decode()
            if sharing.get("hm_notes"):
                result["hm_notes"] = grading.get("summary", "")
        return result

    # ─── audit verification ───────────────────────────────────────────────────

    # ─── GitHub OAuth state storage ───────────────────────────────────────────

    def _github_auth_dir(self) -> Path:
        d = self.data_dir / "github_auth"
        d.mkdir(exist_ok=True)
        return d

    def _github_subs_path(self) -> Path:
        return self.data_dir / "github_submissions.json"

    def save_github_state(self, state: str, code: str) -> None:
        """Create a pending OAuth state record keyed by state UUID."""
        obj = {
            "state": state,
            "code": code,
            "created_at": time.time(),
            "status": "pending",
        }
        self._write_atomic(
            self._github_auth_dir() / f"{state}.json",
            json.dumps(obj, indent=2),
        )

    def get_github_state(self, state: str) -> dict | None:
        """Read an OAuth state record. Returns None if not found."""
        return self._load_json(self._github_auth_dir() / f"{state}.json")

    def update_github_state(self, state: str, updates: dict) -> None:
        """Merge updates into an existing OAuth state record (atomic)."""
        p = self._github_auth_dir() / f"{state}.json"
        obj = self._load_json(p) or {}
        obj.update(updates)
        self._write_atomic(p, json.dumps(obj, indent=2))

    def check_github_duplicate(self, code: str, github_id: int | str) -> bool:
        """Return True if this github_id has already submitted for this code."""
        subs = self._load_json(self._github_subs_path()) or {}
        return str(github_id) in subs.get(code, {})

    def record_github_submission(self, code: str, github_id: int | str, cid: str) -> None:
        """Lock github_id → cid for this interview code (prevents re-submission)."""
        subs = self._load_json(self._github_subs_path()) or {}
        subs.setdefault(code, {})[str(github_id)] = cid
        self._write_atomic(self._github_subs_path(), json.dumps(subs, indent=2))

    # ─── audit verification ───────────────────────────────────────────────────

    def verify_all_chains(self, hm_key: str) -> dict:
        broken = []
        total = 0
        sessions_dir = self._sessions_dir(hm_key)
        if not sessions_dir.exists():
            return {"ok": True, "entries": 0, "message": "No sessions."}
        for code_dir in sessions_dir.iterdir():
            if not code_dir.is_dir():
                continue
            for cid_dir in code_dir.iterdir():
                if not cid_dir.is_dir():
                    continue
                entries = self._load_jsonl(cid_dir / "audit.jsonl")
                prev = "0" * 16
                for i, entry in enumerate(entries):
                    total += 1
                    stored_hash = entry.get("hash", "")
                    check_entry = {k: v for k, v in entry.items() if k != "hash"}
                    expected = self._hash_chain(prev, check_entry)
                    if stored_hash != expected:
                        label = f"{code_dir.name}/{cid_dir.name} entry {i}"
                        broken.append(f"{label}: expected {expected}, got {stored_hash}")
                    prev = stored_hash
        if broken:
            return {"ok": False, "entries": total, "message": f"Hash mismatch: {broken[0]}"}
        return {"ok": True, "entries": total, "message": "Chain intact."}

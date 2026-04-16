"""
interview.core.integrity
------------------------
Verifies the hash chain of a candidate's session (events.jsonl).

The chain works like a linked list:
  event[n].prev_hash == event[n-1].hash
  event[n].hash      == sha256(json(event without hash field), sort_keys=True)[:16]

verify_session() returns a rich result dict suitable for the dashboard UI.
"""

import hashlib
import json
import time
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR  = INTERVIEW_DIR / "sessions"


def _recompute_hash(event: dict) -> str:
    """
    Recompute event hash using the canonical chain construction:
      hash[n] = SHA256(prev_hash_raw || json(body))
    where body excludes both "hash" and "prev_hash" (prev_hash is prepended raw).
    """
    prev_hash = event.get("prev_hash", "")
    body = {k: v for k, v in event.items() if k not in ("hash", "prev_hash")}
    content = json.dumps(body, sort_keys=True)
    return hashlib.sha256((prev_hash + content).encode()).hexdigest()[:16]


def verify_session(code: str) -> dict:
    """
    Walk the session's events.jsonl and verify the hash chain is unbroken.

    Returns:
      {
        "ok":                  bool,
        "event_count":         int,
        "chain_intact":        bool,
        "manifest_ok":         bool,
        "broken_at":           int | None,   # 0-based event index
        "broken_event_type":   str | None,
        "hash_mismatch_count": int,
        "details":             str,
        "session_start":       float | None,
        "session_end":         float | None,
        "elapsed_minutes":     float | None,
        "final_hash":          str,
        "verified_at":         str,          # ISO timestamp of this check
      }
    """
    verified_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    events_file  = SESSIONS_DIR / code / "events.jsonl"
    manifest_file = SESSIONS_DIR / code / "manifest.json"

    if not events_file.exists():
        return {
            "ok": False,
            "event_count": 0,
            "chain_intact": False,
            "manifest_ok": False,
            "broken_at": None,
            "broken_event_type": None,
            "hash_mismatch_count": 0,
            "details": (
                "events.jsonl not found locally. "
                "Click Verify again after the session is cached (grading fetches it automatically)."
            ),
            "session_start": None,
            "session_end": None,
            "elapsed_minutes": None,
            "final_hash": "",
            "verified_at": verified_at,
        }

    # Parse events
    events = []
    for line in events_file.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except Exception:
                return {
                    "ok": False,
                    "event_count": len(events),
                    "chain_intact": False,
                    "manifest_ok": False,
                    "broken_at": len(events),
                    "broken_event_type": "parse_error",
                    "hash_mismatch_count": 1,
                    "details": f"Malformed JSON at line {len(events) + 1} in events.jsonl.",
                    "session_start": None,
                    "session_end": None,
                    "elapsed_minutes": None,
                    "final_hash": "",
                    "verified_at": verified_at,
                }

    if not events:
        return {
            "ok": False,
            "event_count": 0,
            "chain_intact": False,
            "manifest_ok": False,
            "broken_at": None,
            "broken_event_type": None,
            "hash_mismatch_count": 0,
            "details": "events.jsonl is empty.",
            "session_start": None,
            "session_end": None,
            "elapsed_minutes": None,
            "final_hash": "",
            "verified_at": verified_at,
        }

    # Walk the chain
    broken_at = None
    broken_event_type = None
    hash_mismatch_count = 0
    prev_hash = ""

    for i, event in enumerate(events):
        stored_hash = event.get("hash", "")
        stored_prev = event.get("prev_hash", "")

        # 1. Verify prev_hash linkage
        if stored_prev != prev_hash:
            if broken_at is None:
                broken_at = i
                broken_event_type = event.get("type", "?")
            hash_mismatch_count += 1

        # 2. Re-derive hash from event content
        computed = _recompute_hash(event)
        if computed != stored_hash:
            if broken_at is None:
                broken_at = i
                broken_event_type = event.get("type", "?")
            hash_mismatch_count += 1

        prev_hash = stored_hash

    chain_intact = hash_mismatch_count == 0

    # Cross-check manifest.final_hash
    manifest_ok = True
    manifest_note = ""
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text())
            mfh = manifest.get("final_hash", "")
            last_hash = events[-1].get("hash", "")
            if mfh and last_hash and mfh != last_hash:
                manifest_ok = False
                manifest_note = (
                    f" Manifest final_hash ({mfh!r}) does not match "
                    f"last event hash ({last_hash!r}) — manifest was altered after sealing."
                )
        except Exception:
            pass

    # Session timestamps
    session_start = None
    session_end   = None
    for e in events:
        if e["type"] == "session_start":
            session_start = e.get("timestamp")
        if e["type"] == "session_end":
            session_end = e.get("timestamp")

    elapsed_minutes = None
    if session_start and session_end:
        elapsed_minutes = round((session_end - session_start) / 60, 1)

    # Build summary
    ok = chain_intact and manifest_ok
    if ok:
        details = (
            f"Chain intact — {len(events)} events verified, no tampering detected.{manifest_note}"
        )
    else:
        if not chain_intact:
            details = (
                f"Chain broken at event {broken_at} (type: {broken_event_type}) — "
                f"{hash_mismatch_count} hash mismatch(es). "
                f"Session log may have been modified after submission."
            )
        else:
            details = f"Event chain ok.{manifest_note}"

    return {
        "ok":                  ok,
        "event_count":         len(events),
        "chain_intact":        chain_intact,
        "manifest_ok":         manifest_ok,
        "broken_at":           broken_at,
        "broken_event_type":   broken_event_type,
        "hash_mismatch_count": hash_mismatch_count,
        "details":             details,
        "session_start":       session_start,
        "session_end":         session_end,
        "elapsed_minutes":     elapsed_minutes,
        "final_hash":          events[-1].get("hash", "") if events else "",
        "verified_at":         verified_at,
    }

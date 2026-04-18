"""
interview.core.decisions
------------------------
Comments and hiring decisions for a candidate.

Comments:   append-only, timestamped, stored in comments.jsonl
Decisions:  single record per candidate (hire / next_round / reject + reason)
"""

import json
import time
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR = INTERVIEW_DIR / "sessions"


# ─── Comments ─────────────────────────────────────────────────────────────────

def add_comment(code: str, text: str, author: str = "HM") -> dict:
    """
    Append a comment to the candidate's profile.
    Comments are never editable or deletable — append-only.
    Returns the comment record.
    """
    text = text.strip()
    if not text:
        raise ValueError("Comment cannot be empty.")

    comment = {
        "timestamp_ms": int(time.time() * 1000),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "author": author,
        "text": text,
    }

    comment_file = SESSIONS_DIR / code / "comments.jsonl"
    comment_file.parent.mkdir(parents=True, exist_ok=True)
    with open(comment_file, "a") as f:
        f.write(json.dumps(comment) + "\n")

    return comment


def get_comments(code: str) -> list[dict]:
    """Return all comments for a candidate, oldest first."""
    comment_file = SESSIONS_DIR / code / "comments.jsonl"
    if not comment_file.exists():
        return []
    comments = []
    for line in comment_file.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                comments.append(json.loads(line))
            except Exception:
                pass
    return comments


# ─── Decisions ────────────────────────────────────────────────────────────────

VALID_DECISIONS = {"hire", "next_round", "reject"}


def record_decision(
    code: str,
    decision: str,
    reason: str = "",
    author: str = "HM",
) -> dict:
    """
    Record a hiring decision for a candidate.
    Overwrites any previous decision (but the audit log preserves history).
    """
    decision = decision.strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Decision must be one of: {', '.join(VALID_DECISIONS)}")

    record = {
        "timestamp_ms": int(time.time() * 1000),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "decision": decision,
        "reason": reason.strip(),
        "author": author,
    }

    decision_file = SESSIONS_DIR / code / "decision.json"
    decision_file.parent.mkdir(parents=True, exist_ok=True)
    decision_file.write_text(json.dumps(record, indent=2))

    return record


def get_decision(code: str) -> dict | None:
    """Return the current decision for a candidate, or None."""
    decision_file = SESSIONS_DIR / code / "decision.json"
    if decision_file.exists():
        try:
            return json.loads(decision_file.read_text())
        except Exception:
            pass
    return None


# ─── Grade helpers used by dashboard ─────────────────────────────────────────

def is_graded(code: str) -> bool:
    """Return True if a grade has been recorded for this candidate."""
    grading_file = SESSIONS_DIR / code / "grading.json"
    if not grading_file.exists():
        return False
    try:
        g = json.loads(grading_file.read_text())
        return g.get("overall_score") is not None
    except Exception:
        return False


def save_grade(code: str, grading: dict) -> dict:
    """
    Save AI grading result and log the audit event.
    This is what unlocks the Reveal button.
    """
    grading_file = SESSIONS_DIR / code / "grading.json"
    grading_file.parent.mkdir(parents=True, exist_ok=True)
    grading["graded_at_ms"] = int(time.time() * 1000)
    grading["graded_at_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
    grading_file.write_text(json.dumps(grading, indent=2))

    return grading


def record_reveal(code: str) -> dict:
    # No-op — identity is always visible. Kept for compatibility.
    return {}

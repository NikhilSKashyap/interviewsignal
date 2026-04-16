"""
interview.core.audit
---------------------
Append-only, hash-chained audit log for HM actions.
Every significant action is logged locally AND emailed to the audit recipient,
whose mail server provides a tamper-evident external timestamp.

Audit events (HM-side):
  report_opened       HM first views a candidate report
  grade_recorded      HM saves a score — UNLOCKS Reveal
  identity_revealed   HM clicks Reveal (includes delta from grade time)
  comment_added       HM adds a comment to a candidate profile
  next_round_scheduled HM moves candidate forward
  decision_recorded   HM records hire or reject with reason

Local storage: ~/.interview/audit.jsonl  (single append-only file, all sessions)
Email anchor:  silent BCC to audit_email on key events
"""

import hashlib
import json
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Literal

INTERVIEW_DIR = Path.home() / ".interview"
AUDIT_FILE = INTERVIEW_DIR / "audit.jsonl"
CONFIG_FILE = INTERVIEW_DIR / "config.json"

AuditEventType = Literal[
    "report_opened",
    "grade_recorded",
    "identity_revealed",
    "comment_added",
    "next_round_scheduled",
    "decision_recorded",
]

# Events that always trigger an audit email
EMAIL_ANCHOR_EVENTS = {
    "grade_recorded",
    "identity_revealed",
    "comment_added",
    "decision_recorded",
    "next_round_scheduled",
}


# ─── Core append function ─────────────────────────────────────────────────────

def _last_audit_hash() -> str:
    """Read the hash of the last audit event (for chaining)."""
    if not AUDIT_FILE.exists():
        return ""
    lines = AUDIT_FILE.read_text().splitlines()
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                return json.loads(line).get("hash", "")
            except Exception:
                pass
    return ""


def append(event_type: AuditEventType, code: str, payload: dict) -> dict:
    """
    Append one event to the audit log.
    Returns the full event record (including hash) for use in emails.
    """
    INTERVIEW_DIR.mkdir(parents=True, exist_ok=True)

    prev_hash = _last_audit_hash()
    # hash[n] = SHA256(prev_hash_raw || json(body)) — chain dep explicit, not in JSON
    body = {
        "type":          event_type,
        "code":          code,
        "timestamp_ms":  int(time.time() * 1000),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "payload":       payload,
    }
    raw = json.dumps(body, sort_keys=True)
    event = {
        **body,
        "prev_hash": prev_hash,
        "hash": hashlib.sha256((prev_hash + raw).encode()).hexdigest()[:20],
    }

    with open(AUDIT_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")

    return event


def read_events(code: str | None = None) -> list[dict]:
    """Read all audit events, optionally filtered by interview code."""
    if not AUDIT_FILE.exists():
        return []
    events = []
    for line in AUDIT_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if code is None or e.get("code") == code:
                events.append(e)
        except Exception:
            pass
    return events


def verify_chain() -> tuple[bool, str]:
    """
    Walk the entire audit log and verify the hash chain is unbroken.
    Returns (ok: bool, message: str).
    """
    if not AUDIT_FILE.exists():
        return True, "Audit log is empty."

    events = []
    for line in AUDIT_FILE.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except Exception:
                return False, f"Malformed JSON line in audit log."

    for i, event in enumerate(events):
        expected_prev = events[i - 1]["hash"] if i > 0 else ""
        if event.get("prev_hash") != expected_prev:
            return False, (
                f"Chain broken at event {i} ({event.get('type')} / {event.get('code')}) — "
                f"expected prev_hash={expected_prev!r}, got {event.get('prev_hash')!r}"
            )
        # Re-derive hash: SHA256(prev_hash_raw || json(body_without_hash_and_prev_hash))
        body = {k: v for k, v in event.items() if k not in ("hash", "prev_hash")}
        raw = json.dumps(body, sort_keys=True)
        derived = hashlib.sha256((expected_prev + raw).encode()).hexdigest()[:20]
        if derived != event.get("hash"):
            return False, f"Hash mismatch at event {i} ({event.get('type')})"

    return True, f"Audit log intact — {len(events)} events verified."


# ─── Grade timing helpers ─────────────────────────────────────────────────────

def get_grade_timestamp(code: str) -> float | None:
    """Return the Unix timestamp (ms / 1000) when grade was recorded, or None."""
    for e in read_events(code):
        if e["type"] == "grade_recorded":
            return e["timestamp_ms"] / 1000
    return None


def get_reveal_delta(code: str) -> str:
    """
    Return human-readable delta between grade_recorded and identity_revealed.
    e.g. '4 minutes after grade was recorded'
    """
    grade_ts = None
    reveal_ts = None
    for e in read_events(code):
        if e["type"] == "grade_recorded" and grade_ts is None:
            grade_ts = e["timestamp_ms"] / 1000
        if e["type"] == "identity_revealed":
            reveal_ts = e["timestamp_ms"] / 1000

    if grade_ts is None:
        return "identity revealed before any grade was recorded"
    if reveal_ts is None:
        return "not yet revealed"

    delta_seconds = reveal_ts - grade_ts
    if delta_seconds < 0:
        return f"identity revealed {abs(int(delta_seconds))}s BEFORE grade — review required"
    if delta_seconds < 60:
        return f"{int(delta_seconds)} seconds after grade was recorded"
    return f"{round(delta_seconds / 60, 1)} minutes after grade was recorded"


# ─── Email anchoring ─────────────────────────────────────────────────────────

def _load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def _get_audit_email_from_session(code: str) -> str | None:
    """Pull audit_email from the interview manifest."""
    manifest_file = INTERVIEW_DIR / "sessions" / code / "manifest.json"
    if manifest_file.exists():
        try:
            m = json.loads(manifest_file.read_text())
            return m.get("audit_email")
        except Exception:
            pass
    # Fall back to created/ manifest
    created_file = INTERVIEW_DIR / "created" / f"{code}.json"
    if created_file.exists():
        try:
            m = json.loads(created_file.read_text())
            return m.get("audit_email")
        except Exception:
            pass
    return None


def _build_audit_email(event: dict, audit_email: str, hm_email: str) -> MIMEMultipart:
    code = event["code"]
    etype = event["type"]
    ts = event["timestamp_iso"]
    payload = event.get("payload", {})

    subject_map = {
        "grade_recorded": f"[AUDIT] Grade recorded — {code}",
        "identity_revealed": f"[AUDIT] Identity revealed — {code}",
        "comment_added": f"[AUDIT] Comment added — {code}",
        "next_round_scheduled": f"[AUDIT] Next round scheduled — {code}",
        "decision_recorded": f"[AUDIT] Decision recorded — {code}",
    }
    subject = subject_map.get(etype, f"[AUDIT] {etype} — {code}")

    # Build body based on event type
    if etype == "grade_recorded":
        score = payload.get("overall_score", "—")
        dims = payload.get("dimensions", [])
        dim_lines = "\n".join(
            f"  {d['name']:<30} {d['score']}/10  — {d.get('justification','')}"
            for d in dims
        )
        detail = f"Score: {score}/10\n\nDimensions:\n{dim_lines}\n\nReveal is now unlocked."

    elif etype == "identity_revealed":
        delta = get_reveal_delta(code)
        grade_score = payload.get("grade_score_at_reveal", "—")
        detail = (
            f"Candidate identity revealed.\n"
            f"Grade at reveal: {grade_score}/10\n"
            f"Timing: {delta}\n\n"
            f"{'✓ Blind grading confirmed.' if 'before' not in delta else '⚠ REVIEW REQUIRED — revealed before grading.'}"
        )

    elif etype == "comment_added":
        detail = f"Comment:\n\n  \"{payload.get('text', '')}\""

    elif etype == "decision_recorded":
        decision = payload.get("decision", "—").upper()
        reason = payload.get("reason", "No reason provided.")
        detail = f"Decision: {decision}\nReason: {reason}"

    elif etype == "next_round_scheduled":
        detail = f"Candidate moved to next round.\nNotes: {payload.get('notes', '—')}"

    else:
        detail = json.dumps(payload, indent=2)

    body = f"""interviewsignal audit log — {ts}

Interview: {code}
Event:     {etype}
Hash:      {event['hash']}
Chain:     {event['prev_hash'][:10]}... → {event['hash']}

{detail}

---
This audit email was generated automatically by interviewsignal.
It serves as a tamper-evident record of hiring manager actions.
Local audit log: ~/.interview/audit.jsonl
"""

    msg = MIMEMultipart()
    msg["From"] = hm_email
    msg["To"] = audit_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    return msg


def send_audit_email(event: dict):
    """
    Send a silent audit email for the given event.
    Fails silently — a failed audit email is logged locally but never crashes the UI.
    """
    code = event["code"]
    if event["type"] not in EMAIL_ANCHOR_EVENTS:
        return

    audit_email = _get_audit_email_from_session(code)
    if not audit_email:
        return  # No audit email configured — log only

    config = _load_config()
    smtp_host = config.get("smtp_host", "")
    smtp_port = config.get("smtp_port", 587)
    smtp_user = config.get("smtp_user", "")
    smtp_pass = config.get("smtp_pass", "")
    hm_email = config.get("from_email") or smtp_user

    if not smtp_host or not smtp_user:
        return  # SMTP not configured

    try:
        msg = _build_audit_email(event, audit_email, hm_email)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [audit_email], msg.as_string())
    except Exception:
        # Audit email failure must never crash the main flow.
        # Log the failure locally.
        failure_note = {
            "type": "audit_email_failed",
            "code": code,
            "event_hash": event["hash"],
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        }
        with open(AUDIT_FILE, "a") as f:
            f.write(json.dumps(failure_note) + "\n")


# ─── Convenience: log + email in one call ────────────────────────────────────

def log(event_type: AuditEventType, code: str, payload: dict) -> dict:
    """Append to audit log and send email anchor. Returns the event."""
    event = append(event_type, code, payload)
    send_audit_email(event)
    return event

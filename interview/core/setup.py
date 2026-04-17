"""
interview.core.setup
--------------------
Handles HM interview creation: encodes the interview package into a
signed token, stores it (locally or via relay), and returns the interview code.
"""

import argparse
import base64
import hashlib
import json
import os
import random
import string
import time
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR = INTERVIEW_DIR / "sessions"
CREATED_DIR = INTERVIEW_DIR / "created"


def ensure_dirs():
    for d in [INTERVIEW_DIR, SESSIONS_DIR, CREATED_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def generate_code() -> str:
    """Generate a human-readable interview code like INT-4829-XK."""
    digits = "".join(random.choices(string.digits, k=4))
    letters = "".join(random.choices(string.ascii_uppercase, k=2))
    return f"INT-{digits}-{letters}"


def encode_package(payload: dict) -> str:
    """Base64-encode the interview payload for embedding in the code token."""
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode()


def create_interview(
    problem: str,
    rubric: str,
    hm_email: str,
    cc_emails: list[str],
    candidate_email: str | None,
    time_limit_minutes: int | None,
    anonymize: bool = True,
    audit_email: str | None = None,
    sharing: dict | None = None,
) -> dict:
    ensure_dirs()

    code = generate_code()
    created_at = int(time.time())

    # Embed HM's relay config so candidates need zero transport setup
    relay_url = ""
    hm_key = ""
    try:
        from interview.core.transport import get_relay_url, get_hm_key
        relay_url = get_relay_url() or ""
        hm_key = get_hm_key() if relay_url else ""
    except Exception:
        pass

    # Sharing config: what score information candidates can see after submission.
    # Defaults to no sharing (null). HM can override per-code from dashboard.
    sharing_config = sharing or {
        "score":   "none",    # none | overall | breakdown | breakdown_notes
        "debrief": False,     # share Claude's session debrief with candidate
        "hm_notes": False,    # share HM summary/concerns with candidate
    }

    payload = {
        "code": code,
        "problem": problem,
        "rubric": rubric,
        "hm_email": hm_email,
        "cc_emails": cc_emails,
        "candidate_email": candidate_email,
        "time_limit_minutes": time_limit_minutes,
        "anonymize": anonymize,
        "audit_email": audit_email,
        "created_at": created_at,
        "sharing": sharing_config,
        # Integrity: hash of the problem + rubric so candidates can't claim
        # the problem was different
        "problem_hash": hashlib.sha256(problem.encode()).hexdigest()[:16],
        # Transport: relay config flows HM → package → candidate
        # hm_key scopes the session to this HM on the relay (Model B)
        "relay_url": relay_url,
        "hm_key": hm_key,
    }

    # Save locally on HM's machine
    interview_file = CREATED_DIR / f"{code}.json"
    interview_file.write_text(json.dumps(payload, indent=2))

    # Also write an encoded token (for offline/embedded sharing)
    token = encode_package(payload)
    token_file = CREATED_DIR / f"{code}.token"
    token_file.write_text(token)

    # Push to relay so candidates can fetch via code (no file transfer needed)
    if relay_url and hm_key:
        try:
            from interview.core.transport import RelayTransport
            rt = RelayTransport(relay_url, hm_key=hm_key)
            rt.push_interview(code, payload)
        except Exception as e:
            print(f"  ⚠ Could not push interview to relay: {e}")
            print(f"    Candidates will need the token string to start instead.")

    return {"code": code, "payload": payload, "token": token}


def load_interview(code: str) -> dict | None:
    """
    Load an interview package by code.
    Checks local storage first (for candidate who received the full token),
    then falls back to relay lookup.
    """
    # 1. Check local created/ (HM running on same machine — dev/testing)
    local_file = CREATED_DIR / f"{code}.json"
    if local_file.exists():
        return json.loads(local_file.read_text())

    # 2. Check if it's an embedded token (code is actually a token string)
    try:
        decoded = base64.urlsafe_b64decode(code.encode() + b"==")
        payload = json.loads(decoded)
        if "code" in payload and "problem" in payload:
            return payload
    except Exception:
        pass

    # 3. Relay lookup — fetch the package from the relay (no auth needed)
    try:
        from interview.core.transport import get_relay_url, RelayTransport, TransportError
        relay_url = get_relay_url()
        if relay_url:
            rt = RelayTransport(relay_url)
            return rt.get_interview(code)
    except Exception:
        pass

    return None


def main():
    parser = argparse.ArgumentParser(description="Create an interview session")
    parser.add_argument("command", choices=["create"])
    parser.add_argument("--problem-file", required=True)
    parser.add_argument("--rubric-file", required=True)
    parser.add_argument("--hm-email", required=True)
    parser.add_argument("--cc-emails", default="")
    parser.add_argument("--candidate-email", default=None)
    parser.add_argument("--time-limit", type=int, default=None)
    parser.add_argument("--anonymize", action="store_true", default=True)
    parser.add_argument("--no-anonymize", dest="anonymize", action="store_false")
    parser.add_argument("--audit-email", default=None)
    parser.add_argument("--sharing-score", default="none",
                        choices=["none", "overall", "breakdown", "breakdown_notes"],
                        help="What score info candidates can see after submission")
    parser.add_argument("--sharing-debrief", action="store_true", default=False,
                        help="Share Claude's session debrief with candidate")
    parser.add_argument("--sharing-hm-notes", action="store_true", default=False,
                        help="Share HM summary and concerns with candidate")
    args = parser.parse_args()

    problem = Path(args.problem_file).read_text().strip()
    rubric = Path(args.rubric_file).read_text().strip()
    cc_emails = [e.strip() for e in args.cc_emails.split(",") if e.strip()]

    sharing = {
        "score":    args.sharing_score,
        "debrief":  args.sharing_debrief,
        "hm_notes": args.sharing_hm_notes,
    }

    result = create_interview(
        problem=problem,
        rubric=rubric,
        hm_email=args.hm_email,
        cc_emails=cc_emails,
        candidate_email=args.candidate_email,
        time_limit_minutes=args.time_limit,
        anonymize=args.anonymize,
        audit_email=args.audit_email,
        sharing=sharing,
    )

    print(f"\n✓ Interview created.\n")
    print(f"  Code: {result['code']}\n")
    print(f"Share this code with your candidate. They run:\n")
    print(f"  pip install interviewsignal && interview install")
    print(f"  /interview {result['code']}\n")
    print(f"You'll receive the full session report by email when they submit.")
    print(f"To review candidates: /interview dashboard\n")


if __name__ == "__main__":
    main()

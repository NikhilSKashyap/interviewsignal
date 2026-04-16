"""
interview.core.email_sender
----------------------------
Sends the interview report to HM + CC list + candidate.

Uses smtplib by default. Falls back gracefully with a manual-send message
if SMTP is not configured.

Environment variables (set once, stored in ~/.interview/config.json):
  INTERVIEW_SMTP_HOST     e.g. smtp.gmail.com
  INTERVIEW_SMTP_PORT     e.g. 587
  INTERVIEW_SMTP_USER     e.g. yourname@gmail.com
  INTERVIEW_SMTP_PASS     app password (not your real password)
  INTERVIEW_FROM_EMAIL    defaults to SMTP_USER if not set

For Gmail: use an App Password (myaccount.google.com/apppasswords).
For other providers: standard SMTP credentials.
"""

import argparse
import json
import os
import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR = INTERVIEW_DIR / "sessions"
CONFIG_FILE = INTERVIEW_DIR / "config.json"


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def _get_smtp_config() -> dict:
    config = _load_config()
    return {
        "host": os.environ.get("INTERVIEW_SMTP_HOST", config.get("smtp_host", "")),
        "port": int(os.environ.get("INTERVIEW_SMTP_PORT", config.get("smtp_port", 587))),
        "user": os.environ.get("INTERVIEW_SMTP_USER", config.get("smtp_user", "")),
        "password": os.environ.get("INTERVIEW_SMTP_PASS", config.get("smtp_pass", "")),
        "from_email": os.environ.get("INTERVIEW_FROM_EMAIL", config.get("from_email", "")),
    }


def _build_email(
    code: str,
    manifest: dict,
    grading: dict | None,
    html_report_path: str,
) -> MIMEMultipart:
    smtp = _get_smtp_config()
    from_email = smtp["from_email"] or smtp["user"]

    hm_email = manifest["hm_email"]
    cc_emails = manifest.get("cc_emails", [])
    candidate_email = manifest.get("candidate_email")
    if candidate_email and candidate_email not in cc_emails:
        cc_emails = list(cc_emails) + [candidate_email]

    overall = grading.get("overall_score", "—") if grading else "—"
    summary = grading.get("summary", "Not yet graded.") if grading else "Not yet graded."
    elapsed = manifest.get("elapsed_minutes", 0)
    started = time.strftime("%Y-%m-%d %H:%M", time.localtime(manifest["started_at"]))

    # Build dimension table for email body
    dim_rows = ""
    if grading and grading.get("dimensions"):
        for d in grading["dimensions"]:
            dim_rows += f"  {d['name']:<30} {d['score']}/10  —  {d.get('justification', '')}\n"

    body_text = f"""Interview Submission — {code}

Overall Score: {overall} / 10
Duration: {elapsed} minutes
Started: {started}

Summary:
{summary}

Dimension Scores:
{dim_rows if dim_rows else '  (Not yet graded)'}

Full report attached as HTML. Open in any browser.

---
interviewsignal · Thought process, not puzzles.
"""

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = hm_email
    msg["Cc"] = ", ".join(cc_emails)
    msg["Subject"] = f"Interview Submission — {code} — Score: {overall}/10"
    msg.attach(MIMEText(body_text, "plain"))

    # Attach HTML report
    if html_report_path and Path(html_report_path).exists():
        with open(html_report_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="interview_report_{code}.html"',
        )
        msg.attach(part)

    return msg, [hm_email] + cc_emails


def send_report(code: str) -> bool:
    """
    Load the sealed session and send the report email.
    Returns True on success, False on failure.
    """
    session_dir = SESSIONS_DIR / code
    manifest_file = session_dir / "manifest.json"
    grading_file = session_dir / "grading.json"
    html_file = session_dir / "report.html"

    if not manifest_file.exists():
        print(f"✗ No sealed session found for {code}")
        return False

    manifest = json.loads(manifest_file.read_text())
    grading = json.loads(grading_file.read_text()) if grading_file.exists() else None

    smtp = _get_smtp_config()
    if not smtp["host"] or not smtp["user"]:
        print(f"\n  Report ready. Please send it to the hiring manager manually:")
        print(f"  File:  {html_file}")
        print(f"  To:    {manifest['hm_email']}")
        if manifest.get("cc_emails"):
            print(f"  CC:    {', '.join(manifest['cc_emails'])}")
        return True  # not a failure — report is generated, just needs manual delivery

    try:
        msg, all_recipients = _build_email(
            code=code,
            manifest=manifest,
            grading=grading,
            html_report_path=str(html_file),
        )

        with smtplib.SMTP(smtp["host"], smtp["port"]) as server:
            server.starttls()
            server.login(smtp["user"], smtp["password"])
            server.sendmail(smtp["user"], all_recipients, msg.as_string())

        print(f"✓ Report emailed to {manifest['hm_email']}")
        if all_recipients[1:]:
            print(f"  CC: {', '.join(all_recipients[1:])}")
        return True

    except Exception as e:
        print(f"\n⚠ Email send failed: {e}")
        print(f"  Report saved at: {html_file}")
        print(f"  Send it manually to: {manifest['hm_email']}")
        return False


def configure_email_interactive():
    """Walk user through SMTP setup and save to config."""
    print("\nConfigure email sending for interviewsignal")
    print("─" * 45)
    print("You'll need SMTP credentials. For Gmail, use an App Password.")
    print("(myaccount.google.com/apppasswords)\n")

    host = input("SMTP host [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
    port = input("SMTP port [587]: ").strip() or "587"
    user = input("SMTP username (your email): ").strip()
    password = input("SMTP password (app password): ").strip()
    from_email = input(f"From address [{user}]: ").strip() or user

    config = _load_config()
    config.update({
        "smtp_host": host,
        "smtp_port": int(port),
        "smtp_user": user,
        "smtp_pass": password,
        "from_email": from_email,
    })

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    os.chmod(CONFIG_FILE, 0o600)  # restrict permissions on credentials file

    print(f"\n✓ Email configured. Config saved to {CONFIG_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["send", "configure"])
    parser.add_argument("--code", default=None)
    args = parser.parse_args()

    if args.command == "send":
        if not args.code:
            print("✗ --code required")
            return
        send_report(args.code)
    elif args.command == "configure":
        configure_email_interactive()


if __name__ == "__main__":
    main()

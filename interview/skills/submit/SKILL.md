---
name: submit
description: "End an active interviewsignal session: seal the log, generate the report, and email it to the hiring manager. Grading happens on the HM side via the dashboard."
trigger: /submit
---

# /submit

End the active interview session. Run these steps in order:

## Step 1 — Resolve the active session

```bash
python -m interview.core.session status
```

If no active session, tell the user: "No active session. Start one with `/interview <CODE>`." and stop.

Extract the `code` from the output (e.g. `INT-4829-XK`).

## Step 2 — Seal the session

Tell the user: "Sealing session..."

```bash
python -m interview.core.session seal
```

Extract `elapsed_minutes` and `code` from the JSON output.

## Step 3 — Generate report

Tell the user: "Generating report..."

```bash
python -m interview.core.report generate --code <CODE>
```

## Step 4 — Email report to HM

Tell the user: "Sending report..."

```bash
python -m interview.core.email_sender send --code <CODE>
```

If email is not configured, print the report path and HM email so the candidate can send manually. Not a failure.

## Step 5 — Confirm to candidate

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Session submitted — <CODE>

  Session length:  <elapsed>min
  Report sent to:  <hm_email>

  Local copy: ~/.interview/sessions/<code>/

  Good luck.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

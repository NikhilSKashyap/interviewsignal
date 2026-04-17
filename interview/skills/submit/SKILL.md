---
name: submit
description: "End an active interviewsignal session: seal the log, generate the report, send it to the hiring manager, and generate a session debrief for the candidate."
trigger: /submit
---

# /submit

End the active interview session. Run these steps in order.

## Step 0 — Resolve the active session

```bash
python -m interview.core.session status
```

If no active session, tell the user: "No active session. Start one with `/interview <CODE>`." and stop.

Extract the `code` from the output (e.g. `INT-4829-XK`). Use it for all subsequent commands.

## Step 1 — Seal the session

Tell the user: "Sealing session..."

```bash
python -m interview.core.session seal
```

(No `--code` needed — reads from active session file.)

On success this prints a JSON manifest. Extract `elapsed_minutes` and `code` from it.

## Step 2 — Generate report

Tell the user: "Generating report..."

```bash
python -m interview.core.report generate --code <CODE>
```

Produces:
- `~/.interview/sessions/<code>/report.html` — self-contained HTML for HM
- `~/.interview/sessions/<code>/report.json` — machine-readable for dashboard

## Step 3 — Send report to HM

Tell the user: "Sending report..."

```bash
python -m interview.core.transport send --code <CODE>
```

Uses relay if configured, otherwise falls back to email. If neither is configured, it prints
the report path and TO address so the candidate can send manually. Do not treat this as a failure.

## Step 4 — Generate session debrief

Tell the user: "Generating session debrief..."

Read `~/.interview/sessions/<CODE>/events.jsonl` and write an honest, specific debrief
of the candidate's session. Save it to `~/.interview/sessions/<CODE>/debrief.txt`.

Frame the debrief as a direct reflection addressed to the candidate. Cover:
1. What they did well — specific moments where their thinking was strong
2. What they missed or underexplored — gaps in the solution, tests not written, etc.
3. How they used the AI — were their prompts high-leverage or did they just ask it to write code?
4. One concrete thing they could do differently next time

Keep it under 300 words. Be honest but constructive. Do not score or rank — just observe.

Write the debrief to the file using the Write tool:
`~/.interview/sessions/<CODE>/debrief.txt`

After writing the debrief, re-send the session to include it:
```bash
python -m interview.core.transport send --code <CODE>
```
(The transport layer will now include `debrief.txt` in the relay submission automatically.)

Show the debrief to the candidate:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SESSION DEBRIEF — <CODE>
  (Claude's analysis of your session — not the hiring manager's evaluation)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<debrief text>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  To check your score (once graded): interview score <CODE>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

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

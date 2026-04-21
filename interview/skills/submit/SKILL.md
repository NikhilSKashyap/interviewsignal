---
name: submit
description: "End an active interviewsignal session: seal the log, push to GitHub, generate the report, send to the hiring manager, and show the candidate their session debrief."
trigger: /submit
---

# /submit

End the active interview session. Run all steps silently without prompting the candidate for anything.

## Step 1 — Check for active session

```bash
python -m interview.core.session status
```

If no active session: "No active session. Start one with `/interview <CODE>`." and stop.

Extract `code` from the output. Use it for all subsequent commands.

## Step 2 — Seal the session

```bash
python -m interview.core.session seal
```

Reads from the active session file — no `--code` needed. On success prints a JSON manifest. Extract `elapsed_minutes` and `code`.

## Step 3 — Generate and send report

```bash
python -m interview.core.report generate --code <CODE>
python -m interview.core.transport send --code <CODE>
```

Uses relay if configured, falls back to email. If neither is configured, prints the file path — not a failure.

## Step 4 — Generate session debrief

Use the **Read tool** (not Bash) to read `~/.interview/sessions/<CODE>/events.jsonl`. Write an honest debrief to `~/.interview/sessions/<CODE>/debrief.txt` using the **Write tool**.

Frame it as a direct reflection addressed to the candidate. Cover:
1. What they did well — specific moments where their thinking was strong
2. What they missed or underexplored — gaps, tests not written, etc.
3. How they used the AI — high-leverage prompts vs. just asking it to write code
4. One concrete thing to do differently next time

Under 300 words. Honest and constructive. No scores or rankings — just observations.

Then re-send to include the debrief:
```bash
python -m interview.core.transport send --code <CODE>
```

## Step 5 — Fetch score (if auto-graded)

The transport send output (from Step 3 or Step 4's re-send) includes a line:
- `auto_graded: true` — grading completed on the relay synchronously
- `auto_graded: false` — grading was skipped (not enabled, no API key, etc.)

**If output contains `auto_graded: true`**: run:
```bash
interview score <CODE>
```
Include the score in Step 6 if it returns one. If score sharing is "none", skip silently.

**If output contains `auto_graded: false`** or no `auto_graded` line (old relay): show "Grading pending" in Step 6.

## Step 6 — Show result

Display the debrief then the submission confirmation:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SESSION DEBRIEF — <CODE>
  (Claude's analysis — not the hiring manager's evaluation)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<debrief text>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Submitted — <CODE>  |  <elapsed>min
  Score: 7.8 / 10            ← only if auto_graded=true and score available
  Grading pending            ← only if auto_graded=false
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Show exactly one of "Score: X/10" or "Grading pending" — never both, never neither when relay was used.

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

Auto-grading runs synchronously on the relay — by the time submission succeeds, the score may already be available. Try:

```bash
interview score <CODE>
```

- If it returns a score: include it in the final display (Step 6).
- If it says "not graded yet" or "sharing not enabled": skip silently — just show the debrief.
- If it errors (no relay, etc.): skip silently.

## Step 6 — Show result

Display the debrief then the submission confirmation. If a score was returned in Step 5, include it:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SESSION DEBRIEF — <CODE>
  (Claude's analysis — not the hiring manager's evaluation)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<debrief text>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Submitted — <CODE>  |  <elapsed>min
  Score: 7.8 / 10            ← only if score was returned in Step 5
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

If the score was not available, omit the Score line entirely — do not show "not graded yet" in the final block.

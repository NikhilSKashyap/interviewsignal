---
name: submit
description: "End an active interviewsignal session: seal the log, push to GitHub, send to the hiring manager, and show the candidate their score summary."
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

Reads from the active session file — no `--code` needed. On success prints a JSON manifest. Extract `elapsed_minutes`, `code`, and `github_repo_url` (may be null if OAuth wasn't used).

## Step 3 — Generate and send report

```bash
python -m interview.core.report generate --code <CODE>
python -m interview.core.transport send --code <CODE>
```

Uses relay if configured, falls back to email. If neither is configured, prints the file path — not a failure.

The transport send output includes:
- `auto_graded: true` — grading completed on the relay synchronously
- `auto_graded: false` — grading was skipped (not enabled, no API key, etc.)

## Step 4 — Fetch score (if auto-graded)

**If output contains `auto_graded: true`**: run:
```bash
interview score <CODE>
```

**If output contains `auto_graded: false`** or no `auto_graded` line: show "Grading pending" in Step 5.

## Step 5 — Show result

Display the submission block. If `auto_graded: true` and a score was returned in Step 4, include the **full verbatim output** of `interview score <CODE>`.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Submitted — <CODE>  |  <elapsed>min
  Code shared with hiring manager:
    https://github.com/...    ← github_repo_url from manifest (omit if null)

<full verbatim output of `interview score <CODE>` here>
    ← omit entirely if auto_graded=false or score not shared
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

- Show the "Code shared" line only if `github_repo_url` is present in the manifest.
- If `auto_graded: false` (or score not available), replace the score block with:
  `Grading pending — run 'interview score <CODE>' once the HM has graded.`

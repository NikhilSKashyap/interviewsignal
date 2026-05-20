---
name: interview
description: "AI-native interview platform. Type `/interview <CODE>` to start a candidate session — captures all prompts, responses, tool calls, and file changes. Type `/submit` to end the session, seal the log, and send the full thought-process audit to the hiring manager."
trigger: /interview
---

# Interview Skill

---

## Quick Reference

| Command | Who | What |
|---|---|---|
| `/interview <CODE>` | Candidate | Start session, see problem, begin capture |
| `/submit` | Candidate | Seal session, push to GitHub, show eval |
| `/interview status` | Candidate | Show current session status and elapsed time |

---

## Hiring Manager — `/interview hm`

Interview creation has moved to the dashboard. Run `interview dashboard` in your terminal to create interviews, review submissions, and manage grading — all in the browser.

---

## Flow — Candidate Session (`/interview <CODE>`)

Run this command, substituting the actual code:

```bash
python -m interview.core.session start --code INT-4829-XK
```

The command collects identity from config, handles GitHub OAuth (opens a browser tab), and prints the session header and full problem statement. Do not ask the candidate anything before or after running it.

After the command completes, show the full interview banner and problem statement from stdout to the candidate verbatim. Do not add commentary before or after it.

If stdout is not visible in the chat, read `~/.interview/active_session.json` and render the interview code, start time, time limit, and `problem` field as the visible session banner. Wait for the candidate's next message and treat all subsequent work as part of the active interview session.

---

### While the session is active

The hooks capture tool calls automatically. **When the candidate sends a message and you are about to respond**, first log your reasoning:

```bash
python -m interview.core.session log --event-type thinking --payload "{\"plan\":\"YOUR APPROACH HERE\"}"
```

Do this on every substantive candidate turn before you respond. Skip for `/submit` and slash commands. Do NOT run this at session start or unprompted — only in response to a candidate message.

Periodically the hook injects a reminder:
`[interview: session active — INT-4829-XK — 47min elapsed — /submit to end]`

If time limit exceeded:
`[interview: ⚠ time limit reached — type /submit to submit or continue working]`

---

## Submit (`/submit`)

See the `/submit` skill — it handles seal, push, report, and debrief.

---

## Error Handling

**Invalid code:**
```
✗ Interview code INT-XXXX not found or expired.
  Ask the hiring manager to re-share the code.
```

**No active session on /submit:**
```
✗ No active session found.
  Start a session first: /interview <CODE>
```

**GitHub OAuth timed out:**
```
✗ Authentication timed out after 5 minutes. Run /interview INT-4829-XK to try again.
```

**No relay configured:**
Report is saved locally on /submit and the candidate is shown the file path. Not a failure — session continues normally.

---

## Implementation Notes

- Session logs: append-only JSON lines at `~/.interview/sessions/<code>/events.jsonl`
- Each event: `{type, timestamp, prev_hash, payload, hash}` — tamper-evident chain
- Relay stores sealed session server-side; HM grades from dashboard using their own API key

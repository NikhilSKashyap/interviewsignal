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

First, ask the candidate for their identity (two questions, one at a time):

**1.** "What's your name?"
**2.** "What's your email address?"

Then run:

```bash
python -m interview.core.session start \
  --code INT-4829-XK \
  --candidate-name "NAME HERE" \
  --candidate-email "EMAIL HERE"
```

This:
1. Fetches the interview package (validates the code)
2. Auto-configures relay transport from the package — no setup needed
3. GitHub OAuth — if relay has GitHub configured, opens browser for login. One account = one submission.
4. Initialises git in the working directory if not already a repo
5. Creates a public GitHub repo `interview-{code}` and adds it as the `interview` remote (if OAuth succeeded)
6. Starts session recording

If the candidate already submitted (duplicate GitHub account):
```
✗ @username has already submitted for INT-4829-XK.
  Each GitHub account can only submit once per interview.
```
Stop — do not start the session.

Display the session header:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INTERVIEW SESSION — INT-4829-XK
  Started: 2026-04-13 10:32 AM
  GitHub:  @candidate-username
  Repo:    https://github.com/candidate-username/interview-INT-4829-XK
  Time limit: 90 minutes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PROBLEM STATEMENT
  [problem text here]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Session is recording. Type /submit when done.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Then work normally. Do not prompt the candidate for anything else.

### During the session — your responsibility

The hooks capture tool calls automatically. On each substantive user turn (writing code, debugging, explaining approach), log your plan:

```bash
python -m interview.core.session log --event-type thinking --payload '{"plan":"YOUR APPROACH HERE"}'
```

Do this on every substantive turn. Skip for `/submit` and slash commands. The hiring manager grades based on the conversation — missing plans = missing signal.

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

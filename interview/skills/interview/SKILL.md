---
name: interview
description: "AI-native interview platform. Type `/interview hm` to set up an interview as a hiring manager (define problem, rubric, generate candidate code). Type `/interview <CODE>` to start a candidate session — captures all prompts, responses, tool calls, and file changes. Type `/submit` to end the session, grade locally, and email the full thought-process audit to the hiring manager. Type `/interview dashboard` to open the local HM dashboard for reviewing and scoring candidates."
trigger: /interview
---

# Interview Skill

---

## Quick Reference

| Command | Who | What |
|---|---|---|
| `/interview hm` | Hiring Manager | Set up interview: problem, rubric, time → get code |
| `/interview <CODE>` | Candidate | Start session, see problem, begin capture |
| `/submit` | Candidate | Seal session, push to GitHub, show eval |
| `/interview dashboard` | Hiring Manager | Open local dashboard to review candidates |
| `/interview status` | Candidate | Show current session status and elapsed time |

---

## Flow 1 — Hiring Manager Setup (`/interview hm`)

Ask three questions, one at a time:

**1. Problem statement**
"Paste your problem statement."
→ Accept multiline. Store as-is.

**2. Evaluation criteria**
"How should this be evaluated? Describe what you're looking for and how to weight it."
→ Freeform text. Example: "Problem decomposition 40%, code quality 30%, tests 30%"

**3. Time limit**
"Time limit? (e.g. '90 minutes', or Enter for none)"
→ Optional integer (minutes) or null.

Then run, passing problem and rubric as direct arguments:

```bash
python -m interview.core.setup create \
  --problem "PROBLEM TEXT HERE" \
  --rubric "RUBRIC TEXT HERE" \
  --time-limit <MINUTES>
```

(Omit `--time-limit` if none given. Use actual text from the HM's answers — no temp files needed.)

Show the result:

```
✓ Interview created.

  Code: INT-4829-XK

Share this with your candidate:

  pip install interviewsignal && interview install
  /interview INT-4829-XK

To review submissions: interview dashboard
```

---

## Flow 2 — Candidate Session (`/interview <CODE>`)

Run:

```bash
python -m interview.core.session start --code INT-4829-XK
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

## Flow 3 — Submit (`/submit`)

See the `/submit` skill — it handles seal, push, report, and debrief.

---

## Flow 4 — HM Dashboard (`/interview dashboard`)

```bash
python -m interview.dashboard.serve
```

Opens `http://localhost:7832`.

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

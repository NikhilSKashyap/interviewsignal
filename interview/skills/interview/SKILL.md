---
name: interview
description: "AI-native interview platform. Type `/interview hm` to set up an interview as a hiring manager (define problem, rubric, generate candidate code). Type `/interview <CODE>` to start a candidate session — captures all prompts, responses, tool calls, and file changes. Type `/submit` to end the session, grade locally, and email the full thought-process audit to the hiring manager. Type `/interview dashboard` to open the local HM dashboard for reviewing and scoring candidates."
trigger: /interview
---

# Interview Skill

**An AI-native alternative to leetcode.** Captures your entire thought process — prompts, responses, tool calls, diffs — and sends a structured audit to the hiring manager. No contrived puzzles. No whiteboard anxiety. Pure signal.

---

## Quick Reference

| Command | Who | What |
|---|---|---|
| `/interview hm` | Hiring Manager | Set up interview: problem, rubric, emails, generate code |
| `/interview <CODE>` | Candidate | Start session, fetch problem, begin capture |
| `/submit` | Candidate | End session, grade locally, email report to HM |
| `/interview dashboard` | Hiring Manager | Open local dashboard to review + score candidates |
| `/interview status` | Candidate | Show current session status and elapsed time |

---

## Flow 1 — Hiring Manager Setup (`/interview hm`)

When the user types `/interview hm`:

### Step 1: Collect interview parameters

Ask the following, one field at a time (don't dump a form — ask conversationally):

```
1. Problem statement
   "Paste your problem statement. This is what the candidate will see at the start of their session."
   → Accept multiline. Store as-is.

2. Grading rubric
   "How should this session be graded? Describe what you're looking for and how to weight it."
   → Example: "Weight problem decomposition 40%, code quality 30%, testing 20%, AI prompt quality 10%"
   → Store as freeform text. The AI will interpret this at grading time.

3. Time limit
   "Is there a time limit? (e.g. '90 minutes', or press Enter for none)"
   → Optional. Store as minutes integer or null.

4. Your email
   "Your email address (reports will be sent here):"
   → Validate format.

5. CC emails
   "Any additional recipients? (HR, co-interviewer, etc.) Comma-separated, or press Enter to skip:"
   → Optional. Store as list.

6. Candidate email
   "Candidate's email address (they'll receive a CC of their own submission):"
   → Optional. If not provided, candidate enters it at session start.

7. Audit recipient
   "Audit email address — all HM actions (grading, reveals, comments, decisions) are silently logged here. This is what makes the merit claim provable. Typically HR or a neutral party:"
   → Required when anonymize=True. Strongly recommended in all cases.
   → This address receives a silent email on each key action. The mail server's timestamp
     is outside your control — the tamper-evident proof that score came before name.
   → If left blank, audit events are logged locally only (weaker integrity guarantee).

8. Anonymize candidates in the dashboard?
   "Should candidates be anonymized in your dashboard? (yes / no)"
   → If yes: candidates appear as 'Candidate A', 'Candidate B', etc. until you explicitly
     click 'Reveal' on each one. You see scores before you see names — the only way to
     guarantee you're grading the work, not the person.
   → If no: interview codes are shown directly. Useful if you're running a small loop
     and already know who submitted what.
   → Default: yes. Strongly recommended.
   → Store as boolean.
```

### Step 2: Generate the interview code

After collecting all inputs, call the Python backend to create the interview package:

```bash
python -m interview.core.setup create \
  --problem-file /tmp/interview_problem.txt \
  --rubric-file /tmp/interview_rubric.txt \
  --hm-email "..." \
  --cc-emails "..." \
  --candidate-email "..." \
  --audit-email "..."  \
  --time-limit 90 \
  --anonymize          # or --no-anonymize if HM said no
```

This writes the encoded interview package and prints the interview code.

### Step 3: Present the code

```
✓ Interview created.

  Code: INT-4829-XK

Share this code with your candidate. They run:

  pip install interviewsignal && interview install
  /interview INT-4829-XK

You'll receive the full session report by email when they submit.
To review candidates: /interview dashboard
```

---

## Flow 2 — Candidate Session (`/interview <CODE>`)

When the user types `/interview <CODE>` (e.g. `/interview INT-4829-XK`):

### Step 1: Fetch and display the problem

```bash
python -m interview.core.session start --code INT-4829-XK
```

This decodes the interview package, validates the code, prints the problem statement,
and automatically configures the relay transport if the HM embedded one in the package —
so candidates need zero transport setup in the normal flow.

Display it clearly:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INTERVIEW SESSION — INT-4829-XK
  Started: 2026-04-13 10:32 AM
  Time limit: 90 minutes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PROBLEM STATEMENT
  [problem text here]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Session is now recording. Type /submit when done.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 2: Capture begins — your responsibility as the AI assistant

The session hooks capture tool calls automatically. But **you** must capture the conversation.

**At the start of every user turn** (before any other tool calls), run these two commands:

```bash
# 1. Log what the candidate asked
python -m interview.core.session log --event-type user_prompt --payload '{"role":"user","text":"CANDIDATE MESSAGE"}'

# 2. Log your plan before acting
python -m interview.core.session log --event-type thinking --payload '{"plan":"WHAT YOU WILL DO AND WHY"}'
```

Replace `CANDIDATE MESSAGE` with the candidate's exact words and `WHAT YOU WILL DO AND WHY` with your actual approach. Use single quotes around the JSON — if the text itself contains a single quote/apostrophe, omit it or rephrase slightly.

**Skip logging only for**: slash commands (`/submit`, `/interview status`), and trivial one-word replies.

This is the thought-process signal the hiring manager is paying for. Tool calls alone don't show reasoning — your logs do. Every turn should have a `user_prompt` + `thinking` pair.

### Step 3: Remind candidate of active session

Periodically (every tool call), the hook injects a subtle reminder into the tool result:
`[interview: session active — INT-4829-XK — 47min elapsed — /submit to end]`

If a time limit is set and it's exceeded, surface a warning:
`[interview: ⚠ time limit reached — type /submit to submit or continue working]`

---

## Flow 3 — Submit (`/submit`)

When the user types `/submit`, run these four steps in sequence.
Resolve the active interview code first:

```bash
python -m interview.core.session status
```

This prints the active code (e.g. `INT-4829-XK`). Use it for all subsequent commands.
If no active session exists, tell the user: "No active session. Start one with /interview <CODE>."

---

### Step 1: Seal the session

Tell the user: "Sealing session..."

```bash
python -m interview.core.session seal
```

(No `--code` needed — reads from active session file.)

On success this prints a JSON manifest. Extract `elapsed_minutes` and `code` from it.

---

### Step 2: Generate report

Tell the user: "Generating report..."

```bash
python -m interview.core.report generate --code <CODE>
```

Produces:
- `~/.interview/sessions/<code>/report.html` — self-contained HTML for HM
- `~/.interview/sessions/<code>/report.json` — machine-readable for dashboard

---

### Step 3: Send report to HM

Tell the user: "Sending report..."

```bash
python -m interview.core.transport send --code <CODE>
```

This automatically uses the relay if `relay_url` is configured in `~/.interview/config.json`,
otherwise falls back to email. If neither is configured, it prints the report path and TO
address so the candidate can send it manually. Do not treat this as a failure.

---

### Step 4: Confirm to candidate

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Session submitted — <CODE>

  Session length:  <elapsed>min
  Report sent to:  <hm_email>

  Local copy: ~/.interview/sessions/<code>/

  Good luck.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Flow 4 — HM Dashboard (`/interview dashboard`)

When the user types `/interview dashboard`:

```bash
python -m interview.dashboard.serve
```

Opens a local web server at `http://localhost:7832` and launches in browser.

The dashboard reads from `~/.interview/received/` — HM saves report JSONs there from email attachments.

Features:
- Candidate list (anonymous by default — shows Candidate A, B, C)
- Columns: score, time taken, submission date, status (graded/pending)
- **Grade Selected** — run AI grading on selected candidates
- **Grade All** — run AI grading on all pending submissions
- Click candidate → full transcript view + diff view + dimension scores
- **Reveal identity** button (per candidate, explicit click to unmask)
- **Schedule next round** — opens email compose with candidate

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

**No transport configured (fallback at session start):**
```
⚠  No relay configured for this interview.
   Your report will be saved locally on /submit.
   You'll be shown the file path and asked to send it to the hiring manager.
```
This is fine — the report is generated and saved locally. Do not ask the candidate to configure email or SMTP. Just continue with the session.

**Email send failure:**
```
⚠ Report generated but email failed to send.
  Report saved locally: ~/.interview/sessions/<code>/report.html
  Send it manually to: hiring@company.com
```

---

## Implementation Notes

- Session logs are append-only JSON lines: `~/.interview/sessions/<code>/events.jsonl`
- Each event: `{type, timestamp, content_hash, payload}`
- Hash chain: each event includes `prev_hash` — tamper-evident without a server
- The relay (if used) stores only `{code, encrypted_payload}` — no transcripts, no emails
- Email uses the system's configured SMTP or falls back to `smtplib` with user-provided credentials
- All AI grading runs locally through the active AI coding assistant session

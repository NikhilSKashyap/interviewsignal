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

9. Candidate score sharing — what can candidates see after submission?
   "After you grade, candidates can optionally run 'interview score <CODE>' to see their results.
    What would you like to share? Options:
      1. Nothing (default) — candidates see no score
      2. Overall score only — they see a single number (e.g. 7.5/10)
      3. Score breakdown — overall + per-dimension scores
      4. Full breakdown + notes — scores, HM summary, standout moments, concerns"
   → Default: 1 (nothing). Recommend 3 or 4 for transparent hiring loops.
   → Map to: none | overall | breakdown | breakdown_notes
   → Store as sharing.score.

10. Share Claude's session debrief?
    "After /submit, Claude generates a session reflection — what the candidate did well,
     missed, and could improve. Share this with the candidate?"
    → Only shown if sharing.score is not 'none'.
    → Default: no.
    → Store as sharing.debrief (boolean).

11. Share HM notes?
    "Should candidates see the HM summary and concerns from the grading rubric?"
    → Only relevant if sharing.score == 'breakdown_notes'.
    → Default: no.
    → Store as sharing.hm_notes (boolean).
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
  --sharing-score breakdown_notes   # or: none | overall | breakdown
  --sharing-debrief    # omit if no
  --sharing-hm-notes   # omit if no
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

### Step 1: Authenticate and start the session

```bash
python -m interview.core.session start --code INT-4829-XK
```

This command:
1. Fetches the interview package from the relay (validates the code)
2. **GitHub OAuth** — if the relay has GitHub configured, opens the browser for GitHub login.
   The candidate must authorize the app; the CLI polls until complete.
   One GitHub account = one submission. Duplicate attempts are blocked here.
3. Prints the problem statement
4. Begins session recording

If the relay has no GitHub app configured, step 2 is skipped (self-reported identity only).

Display the session header clearly:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INTERVIEW SESSION — INT-4829-XK
  Started: 2026-04-13 10:32 AM
  GitHub:  @candidate-username
  Time limit: 90 minutes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  PROBLEM STATEMENT
  [problem text here]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Session is now recording. Type /submit when done.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

If the candidate has already submitted (duplicate GitHub account), show:
```
  ✗ @username has already submitted for INT-4829-XK.
    Each GitHub account can only submit once per interview.
```
Then stop — do not start the session.

### Step 2: Capture begins — your responsibility as the AI assistant

The session hooks capture tool calls automatically. User prompts and your responses are
captured by the Stop hook at the end of each turn — you do not need to log them manually.

When you see the `INTERVIEW CAPTURE` banner at the start of a new user turn, log your plan:

```bash
python -m interview.core.session log --event-type thinking --payload '{"plan":"YOUR APPROACH HERE"}'
```

Replace the placeholder with your actual approach. Use single quotes around the JSON payload.

**Do this on every substantive user turn** — when the candidate asks you to write code, debug
something, explain an approach, run tests, etc. Skip for `/submit` and slash commands.

The hiring manager grades based on the conversation, not just the tool calls. Missing plans = missing signal.

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

### Step 4: Generate session debrief

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

Show the debrief to the candidate with a SESSION DEBRIEF header block so they can read it:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SESSION DEBRIEF — <CODE>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
<debrief text>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  To check your score (once graded): interview score <CODE>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Note:** The debrief is always shown to the candidate. Whether it is _also_ shared via
`interview score` is the HM's choice (controlled in the dashboard sharing settings).

---

### Step 5: Confirm to candidate

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
- **Score sharing controls** — per-interview toggle on candidate detail page:
  - Score detail level: none / overall / breakdown / breakdown + notes
  - Toggle: share Claude's session debrief with candidate
  - Toggle: share HM summary and concerns with candidate
  - Changes take effect immediately; candidates run `interview score <CODE>` to see results

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

**Candidate already submitted (GitHub duplicate):**
```
✗ @username has already submitted for INT-4829-XK.
  Each GitHub account can only submit once per interview.
```
Do not start the session. The relay enforces this — it is not possible to work around.

**GitHub OAuth timed out:**
```
✗ Authentication timed out after 5 minutes. Run /interview INT-4829-XK to try again.
```
Tell the candidate to re-run the command and complete the browser authorization promptly.

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

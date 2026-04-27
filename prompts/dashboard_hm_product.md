# Prompt: Dashboard as HM product

Paste this into Claude Code. Run from the interviewsignal project root.

---

## Context

The HM experience should be 100% browser. `interview dashboard` is the only command an HM ever runs. Candidates stay 100% terminal (`/interview CODE` in Claude Code / Codex).

Read CLAUDE.md first — the key decisions section has the full rationale. The relevant entries:
- "HM experience is 100% browser"
- "First-run setup wizard in dashboard"
- "HM setup is 3 fields in dashboard form"

## What to build

### 1. First-run setup wizard in dashboard

When `interview dashboard` launches and `~/.interview/config.json` is missing or incomplete (no `relay_url` or no `hm_key`), the dashboard should show a setup wizard instead of the normal candidate list.

**Screen 1 — Relay setup**
- Heading: "Welcome to interviewsignal"
- Brief explanation: "You need a relay to collect candidate submissions. Deploy your own (~$5/mo on Railway) or self-host."
- Input field: "Relay URL" (e.g. `https://myrelay.up.railway.app`)
- "Connect" button → calls `POST /register` on that relay URL, stores `relay_url` and `hm_key` in `~/.interview/config.json`
- On success, advance to screen 2
- On failure, show inline error ("Could not connect to relay — check the URL")
- Link to Railway deploy button / docs for people who don't have a relay yet

**Screen 2 — API key for grading**
- Heading: "Grading setup"
- Explanation: "To auto-grade submissions, enter your Anthropic API key. Grading runs locally — your key is never sent to the relay."
- Input field: "Anthropic API key" (password-masked)
- "Save" button → stores `anthropic_api_key` in `~/.interview/config.json`
- "Skip" option → HM can grade manually from dashboard later
- On save/skip, advance to screen 3

**Screen 3 — Create your first interview**
- This IS the "Create Interview" form described below. After creating the first interview, redirect to the normal dashboard showing the new interview code.

### 2. "Create Interview" form in the dashboard

Add a "Create Interview" button to the dashboard header (visible on the candidate list page). Clicking it shows a form:

**Fields:**
- Problem statement (textarea, required)
- Grading rubric (textarea, required — show the default rubric as placeholder text so the HM can see the format, same default rubric from SKILL.md)
- Time limit in minutes (number input, optional)

**On submit:**
- Call `setup.create_interview()` from the dashboard HTTP handler. The function is already in `interview/core/setup.py`. Pass `hm_email=""`, `cc_emails=[]`, `candidate_email=None`, `audit_email=None` (email fields are vestigial in relay mode).
- Show success page with the interview code, copy-to-clipboard button, and the candidate install command:
  ```
  pip install interviewsignal && interview install
  /interview INT-XXXX-XX
  ```
- "Go to Dashboard" button to return to the candidate list

**Dashboard HTTP handler:**
- Add `POST /create-interview` route to `serve.py`
- Parse form body (problem, rubric, time_limit)
- Import and call `create_interview()` from `interview.core.setup`
- Return the success page with the code

### 3. Update the `/interview` skill to be candidate-only

Edit `interview/skills/interview/SKILL.md`:
- Remove "Flow 1 — Hiring Manager Setup (`/interview hm`)" entirely
- Remove `/interview hm` from the Quick Reference table
- Remove `/interview dashboard` from the Quick Reference table (it's a CLI command, not a skill command)
- Keep "Flow 2 — Candidate Session (`/interview <CODE>`)" as the only flow
- Update the skill description to reflect candidate-only usage
- When someone types `/interview hm`, respond with: "Interview creation has moved to the dashboard. Run `interview dashboard` in your terminal to create interviews, review submissions, and manage grading — all in the browser."

### 4. Wire up `cli.py` — ensure `interview dashboard` is the entry point

Check `interview/cli.py`:
- `interview dashboard` should be the primary HM command
- `interview configure-relay` and `interview configure-api-key` should still work as CLI fallbacks for advanced users / scripting, but the dashboard wizard is the primary path
- Do NOT remove configure-relay / configure-api-key from CLI — they're useful for automation and relay operators

### 5. Dashboard styling

The dashboard already has a dark-mode UI. Match the existing style. The setup wizard and create-interview form should feel like part of the same product, not a separate page. Use the same CSS variables, fonts, and layout patterns already in serve.py's HTML.

The form should be clean and minimal — no framework, no external CSS. Just the same inline styles the dashboard already uses.

## Constraints (from CLAUDE.md)

- Zero external dependencies — stdlib only. No Flask, no Jinja. The dashboard is `http.server` with inline HTML, same as today.
- All file writes atomic — write to `.tmp` then rename
- setup.py's `create_interview()` is the single source of truth for interview creation. The dashboard calls it, doesn't reimplement it.
- Config stored in `~/.interview/config.json` (permissions: 600)

## Files to modify

- `interview/dashboard/serve.py` — add setup wizard routes, create-interview route, update HTML
- `interview/skills/interview/SKILL.md` — remove Flow 1 (HM setup), make candidate-only
- `interview/cli.py` — verify `interview dashboard` works as described (may need no changes)
- `interview/core/setup.py` — may need minor changes if create_interview() needs to be callable without email args (make them all optional with defaults)

## Verification

After implementation:
1. Delete `~/.interview/config.json` and run `interview dashboard` — should show setup wizard
2. Complete setup wizard with a relay URL — should store config and show create-interview form
3. Create an interview from the form — should return a code and the code should be fetchable from the relay
4. Navigate to dashboard — should show the new interview in the list (no candidates yet)
5. Run `/interview <CODE>` in a separate terminal — should work as before (candidate flow unchanged)
6. Type `/interview hm` in Claude Code — should get the redirect message pointing to dashboard

# Architecture

interviewsignal has two logical sides — **candidate** and **hiring manager** — that never need to communicate in real time. The only data exchange is a session report emailed from the candidate's machine to the HM after submission.

```
Candidate machine                 HM machine
─────────────────────             ──────────────────────
~/.interview/sessions/<code>/     ~/.interview/received/<code>/
  events.jsonl (append-only)        report.json  (copied from email)
  manifest.json (sealed)            grading.json (local, from dashboard)
  grading.json                      audit.jsonl  (local HM actions)
  report.html
```

---

## Module responsibilities

### `interview/core/setup.py`
Creates interview packages. Called by `/interview hm`.

- `create_interview(...)` — takes problem, rubric, emails, options. Generates a code like
  `INT-4829-XK`. Stores the full interview payload in `~/.interview/created/<code>.json`.
- The payload is self-contained: everything needed to start a session is in that one file,
  so the candidate doesn't need network access to the HM's machine.
- Codes are random (adjective + noun + digit suffix) but could be sequential in a relay setup.

### `interview/core/session.py`
Manages candidate sessions.

- `start_session(code)` — reads the interview payload, opens `events.jsonl`, logs `session_start`,
  records `~/.interview/active_session.json` (single active session per machine).
- Creates a GitHub repo `interview-{code}` via the GitHub API after OAuth. Initialises a
  `interview` git remote in the working directory with an initial commit.
- `log_event(type, payload)` — appends to `events.jsonl` with a SHA-256 hash chain.
  Each event includes `prev_hash`, so any tampered event breaks the chain.
- `seal_session()` — finalises the session: captures git diff (start commit → HEAD), writes
  `manifest.json` with elapsed time, event count, and final hash.
- `get_session_status()` — reads `active_session.json`, returns elapsed time and event count.

### `interview/hooks/claude_hook.py`
Claude Code PreToolUse/PostToolUse hook.

- Receives tool events via stdin (JSON from Claude Code's hook protocol).
- `handle_pre_tool_use()` — calls `session.log_event("tool_call", ...)`, injects a one-line
  session reminder into the tool result so the candidate sees `[interview: active — 47min]`.
- `handle_post_tool_use()` — calls `session.log_event("tool_result", ...)` with a content hash
  for large outputs (file contents are hashed, not stored, for privacy).
- Installed via `settings.json` hooks; runs as a subprocess for every tool call.

### `interview/core/grader.py`
AI grading via the Anthropic Messages API. Zero external dependencies (stdlib `urllib` only).

- `build_transcript(code)` — converts `events.jsonl` into a human-readable timeline string
  that fits in a prompt. Tool calls are summarised concisely, not reproduced in full.
- `_build_grading_prompt(manifest, transcript)` — assembles the grading prompt with problem,
  rubric, session stats, timeline, and git diff. Instructs the model to return structured JSON.
- `grade_session(code)` — calls the API, parses the JSON response, saves `grading.json`,
  and calls `decisions.save_grade()` to audit-log the grading event.
- API key from `ANTHROPIC_API_KEY` env or `~/.interview/config.json`.

### `interview/core/report.py`
Generates the HM-facing HTML report and machine-readable JSON.

- `generate_html_report(code)` — reads manifest + events + grading, produces a dark-mode
  self-contained HTML with: problem statement, grading scores with bar charts, session
  timeline, syntax-highlighted git diff, and hash-chain integrity block.
- `generate_report(code)` — writes `report.html` and `report.json` to the session directory.
- The HTML is self-contained (no external resources) so it can be emailed as an attachment
  and opened without network access.

### `interview/core/email_sender.py`
Sends session reports via SMTP.

- `send_report(code)` — reads config, attaches `report.html`, sends to HM + CC + candidate.
- `configure_email_interactive()` — interactive wizard to set SMTP credentials.
- Config stored in `~/.interview/config.json` (permissions: 600).
- If not configured, prints the report path and TO address for manual sending.

### `interview/core/audit.py`
Hash-chained audit log for HM actions.

- `append(event_type, code, extra)` — appends an audit event to `~/.interview/audit.jsonl`.
  Each event includes timestamp, prev_hash, and a SHA-256 hash. Any tampered event breaks
  the chain.
- `log(event_type, code, extra)` — calls `append()` and silently emails the event to the
  designated audit recipient. The mail server's timestamp is the external anchor.
- `verify_chain()` — walks the entire log and verifies every hash. Returns `(ok, message)`.
- `get_reveal_delta(code)` — returns human-readable string: "4.8 minutes after grade was
  recorded". This is the provable meritocracy artifact — score before name, in writing.

### `interview/core/decisions.py`
HM decisions — grading, comments, hire/reject, identity reveal.

- `save_grade(code, grading)` — saves `grading.json`, records `graded_at_ms`, calls
  `audit.log("grade_recorded")`. Unlocks the Reveal button.
- `record_reveal(code)` — saves `revealed_at_ms` to manifest, calls `audit.log("identity_revealed")`
  with the delta from grade time.
- `add_comment(code, text)` — appends to `comments.jsonl`, calls `audit.log("comment_added")`.
- `record_decision(code, decision, reason)` — writes `decision.json`, calls
  `audit.log("decision_recorded")`.
- `is_graded(code)` — checks `grading.json` has `overall_score`. Controls Reveal availability.

### `interview/dashboard/serve.py`
Local HM dashboard at `http://localhost:7832`.

- Single-file HTTP server using `http.server.BaseHTTPRequestHandler`.
- Reads from `~/.interview/received/` (HM saves report JSONs from email attachments here).
- Routes: `GET /` (candidate list), `GET /candidate` (detail), `GET /audit` (audit trail),
  `POST /grade`, `POST /reveal`, `POST /add-comment`, `POST /record-decision`.
- `_apply_labels(candidates)` — respects per-interview `anonymize` flag. Anonymous interviews
  show "Candidate A/B/C"; non-anonymous show the code directly.
- Grade-before-Reveal is enforced at the handler level: `/reveal` returns 403 if `is_graded()`
  is False.

### `interview/cli.py`
The `interview` command.

- `install` — copies SKILL.md to `~/.claude/skills/interview/`, updates CLAUDE.md with skill
  description and trigger instructions, installs PreToolUse/PostToolUse hooks in settings.json.
- `uninstall` — reverses install.
- `configure-email` — interactive SMTP setup.
- `configure-api-key` — stores Anthropic key with `chmod 600`.
- `dashboard` — launches `serve.py`.
- `status` — prints active session state.

---

## Data flow: candidate submission

```
/interview INT-4829-XK
  → session.start_session("INT-4829-XK")
    → reads ~/.interview/created/INT-4829-XK.json
    → GitHub OAuth → creates interview-INT-4829-XK GitHub repo
    → git init + git remote add interview <repo_url>
    → git commit --allow-empty -m "session start"
    → writes ~/.interview/active_session.json
    → appends session_start to events.jsonl

[every tool call]
  → claude_hook.py pre   → log_event("tool_call", ...)
  → claude_hook.py post  → log_event("tool_result", ...)

/submit
  → session.seal_session()
    → git add -A && git commit -m "session end"
    → git push interview HEAD:main (clears credentials after push)
    → captures git diff
    → writes manifest.json (with github_repo_url)
  → grader.grade_session(code)
    → build_transcript()  → calls Anthropic API
    → saves grading.json
    → audit.log("grade_recorded")
  → report.generate_report(code)
    → writes report.html + report.json
  → email_sender.send_report(code)
    → emails report.html to HM + CC + candidate
```

## Data flow: HM review

```
[receive email, save attachment to ~/.interview/received/]

interview dashboard
  → serve.py at localhost:7832
  → GET /  → _apply_labels() → show anonymous scores
  → POST /grade  → grade_session()  → save grading.json
  → POST /reveal  → check is_graded()  → record_reveal()
  → POST /add-comment  → add_comment()
  → POST /record-decision  → record_decision()
```

---

## Adding a new platform

Each platform is a ~30-line function in `cli.py`:

1. Add an entry to `PLATFORMS` dict with the relevant install paths.
2. Write `_install_<platform>(verbose=True)` that:
   - Copies or references SKILL.md in whatever format the platform reads skills/rules
   - Wires up `interview.hooks.claude_hook pre/post` as PreToolUse/PostToolUse equivalents
3. Add the platform to `_install_*` dispatch in `cmd_install()`.
4. Add to `PLATFORMS` in the CLI argument choices.

The hook protocol is platform-specific, but the core logic in `claude_hook.py` reads
from stdin and can be adapted to any stdin/stdout-based hook system.

---

## Non-goals

- **No relay server required.** The package is self-contained. Codes are long enough to embed
  the full payload. A relay is Phase 2 for human-readable short codes.
- **No real-time monitoring.** The HM sees the full session only after submission. This is
  intentional — real-time monitoring would change candidate behaviour.
- **No file contents in the log.** Events record file paths and content hashes, not raw content.
  The git diff provides a clean, reviewable view of what was written.

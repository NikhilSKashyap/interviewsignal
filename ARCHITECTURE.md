# Architecture

interviewsignal has two logical sides — **candidate** and **hiring manager** — connected by a
relay server. Session data flows candidate machine → relay → HM dashboard. Email is a fallback
for teams that cannot or do not want to run a relay.

```
Candidate machine                   Relay (relay.interviewsignal.dev or self-hosted)
─────────────────────               ─────────────────────────────────────────────────
~/.interview/sessions/<code>/       /data/hms/<hm_key>/
  events.jsonl  (append-only,         sessions/<code>/<cid>/
                hash-chained)           manifest.json, events.jsonl
  manifest.json (sealed)               flags.json, grading.json
  report.html   (local only)           grading_history.jsonl
  report.json   (local only)           comments.jsonl, decision.json
  active_session.json                  audit.jsonl, meta.json
                                    interviews/<code>.json
                                    sharing/<code>.json

                                    HM dashboard (localhost:7832)
                                      reads from relay in relay mode
                                      reads ~/.interview/received/ in email mode
```

---

## Module list

### `interview/cli.py`
The `interview` command. Entry point for all CLI subcommands: `install`, `uninstall`,
`configure-relay`, `configure-email`, `configure-api-key`, `configure-llm`,
`configure-github-app` (hidden), `dashboard`, `status`, `score`.
`interview install` writes PreToolUse/PostToolUse/Stop hooks to `~/.claude/settings.json`
and adds permissions so all `python -m interview.core.*` commands run without prompts.

### `interview/core/setup.py`
HM interview creation. `create_interview()` generates a code like `INT-4829-XK`, builds a
self-contained interview payload (problem, rubric, relay_url, hm_key, sharing config, etc.),
stores it locally in `~/.interview/created/<code>.json`, and pushes it to the relay so
candidates can fetch it by code. `load_interview(code)` loads a package by trying local
storage first, then base64-embedded token, then relay lookup.

### `interview/core/session.py`
Candidate session lifecycle. `start_session()` runs GitHub OAuth via the relay (if configured),
creates a GitHub repo via the API, initialises a git remote, and writes `active_session.json`.
`log_event()` appends events to `events.jsonl` with SHA-256 hash chain. `seal_session()` runs
on `/submit`: captures final git diff, commits and pushes code to GitHub, writes `manifest.json`
with the final hash and elapsed time. `github_token` is never written to `manifest.json`.

### `interview/core/transport.py`
Transport abstraction. `get_transport()` reads `~/.interview/config.json` and returns either
`RelayTransport` (if `relay_url` is set) or `EmailTransport`. All code that sends or fetches
sessions must go through this factory — never SMTP or direct file reads outside this layer.
`RelayTransport` uses stdlib `urllib` only. Auth is `Bearer <hm_key>` for HM routes; open
routes (interview fetch, score fetch) send no auth header.

### `interview/core/flags.py`
Session quality and tamper detection flags. `compute_flags(events, manifest)` runs all checks
and returns a list of flag dicts (each with `id`, `severity` `"red"|"yellow"`, `label`, `detail`).
All functions are pure — no side effects, no network calls.

**Session quality flags** — computed from session statistics:
- `too_fast`: elapsed time below threshold (< 10 min by default)
- `few_interactions`: fewer than 3 tool calls
- `no_iteration`: no failed-then-retried tool pattern
- `uniform_timing`: event intervals statistically too uniform (possible scripting)
- `no_prompts`: zero user_prompt or thinking events

**Tamper detection flags** — cross-check event log against external signals:
- `hooks_gap`: longest gap between events > 33% of elapsed time (red if > 50%); suggests hooks disabled mid-session
- `diff_event_mismatch`: git diff line count vs Write/Edit tool call count mismatch; catches code written outside the AI assistant
- `prompt_event_ratio`: many tool calls but zero or near-zero prompts; signals partial hook disable

All checks wrapped in `try/except` — a failing check produces no flag rather than crashing.

### `interview/core/grader.py`
AI grading via the Anthropic Messages API (zero external dependencies — `urllib` only).
`build_transcript()` converts `events.jsonl` into a timestamped human-readable timeline.
`grade_session()` loads the local manifest + events, calls the API, parses structured JSON
output, and saves via `decisions.save_grade()`. Supports Anthropic format and OpenAI-compatible
format (`api_format` config key) for enterprise proxies. Default model: `claude-haiku-4-5`.
Grading is HM-only — not triggered at candidate `/submit`.

### `interview/core/decisions.py`
HM-side state: grades, comments, hire/reject decisions, and the no-op reveal function.
`save_grade()` writes `grading.json` and logs the grading event.
`record_reveal()` is a no-op — identity is always visible; kept for API compatibility.
`add_comment()` appends to `comments.jsonl` (append-only; no edit or delete).
`record_decision()` writes `decision.json`; valid values: `hire`, `next_round`, `reject`.
These functions operate on local files in email mode; in relay mode the dashboard posts
results to the relay via `transport.post_action()`.

### `interview/core/audit.py`
Hash-chained audit log for HM actions, stored at `~/.interview/audit.jsonl`. Each event
has `type`, `code`, timestamps, `prev_hash`, and `hash`. Significant events are also silently
emailed to an audit recipient (if SMTP is configured) — the mail server timestamp is the
external anchor for provability. `verify_chain()` re-derives every hash and confirms linkage.
This is the HM-side audit log; the relay has its own per-session `audit.jsonl`.

### `interview/core/integrity.py`
Verifies the hash chain of a candidate's `events.jsonl`. `verify_session()` walks every event,
re-derives its hash from `prev_hash + json(body)`, and checks that `manifest.final_hash` matches
the last event hash. Returns a rich result dict used by the dashboard UI.

### `interview/core/report.py`
Generates the HM-facing HTML report and machine-readable JSON from a sealed session.
`generate_report(code)` reads manifest + events + grading and writes `report.html` (dark-mode,
self-contained, no external resources) and `report.json` to the session directory. Used by email
mode for attachments. Not uploaded to the relay — the dashboard transcript view supersedes it.

### `interview/core/email_sender.py`
SMTP send for email-mode (fallback transport). `send_report()` attaches `report.html` and sends
to HM + CC + candidate. `configure_email_interactive()` is the interactive setup wizard. Config
stored in `~/.interview/config.json` (permissions: 600).

### `interview/hooks/claude_hook.py`
Claude Code PreToolUse, PostToolUse, and Stop hooks installed by `interview install`.

- **PreToolUse**: logs `tool_call` events with hash chain. On new candidate turns (gap > 30s),
  injects a `thinking` prompt asking Claude to log its plan before acting. Mid-turn calls get
  a minimal status line. Session-log Bash calls are skipped to avoid double-logging.
- **PostToolUse**: logs `tool_result` events; hashes large outputs rather than storing them.
- **Stop**: reads `~/.claude/projects/<cwd-hash>/conversations/<session_id>.jsonl` to extract
  the last user message and assistant response from this turn, then logs them as `user_prompt`
  and `assistant_message` events. This makes prompt capture reliable without relying on injected
  instructions. Guards against infinite loops via `stop_hook_active` flag.

### `interview/relay/server.py`
Multi-tenant relay HTTP server (pure stdlib). Binds to `0.0.0.0:8080` by default.
Auth model: `POST /register` and `GET /interviews/{code}` are open. All other routes require
`Bearer <hm_key>` (from `POST /register`) or the master `RELAY_API_KEY` (operator access).
Implements GitHub OAuth flow: `GET /auth/github/start`, `GET /auth/github/callback`,
`GET /auth/github/poll`. Enforces one-account-one-submission per interview code at session
submission time. Environment variables: `RELAY_API_KEY`, `RELAY_DATA_DIR`, `RELAY_PORT`,
`RELAY_BASE_URL`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`.

### `interview/relay/store.py`
File-based multi-tenant session store. Layout: `/data/hms/<hm_key>/interviews/` and
`/data/hms/<hm_key>/sessions/<code>/<cid>/`. All writes are atomic (write `.tmp`, rename).
`record_reveal()` is a no-op — identity fields are always present in `meta.json` and returned
by `get_session()`. `revise_grade()` archives the current grade to `grading_history.jsonl`
before overwriting `grading.json`. `get_session()` includes `debrief` (from `debrief.txt` if
present). `_summarise_candidates()` reads `elapsed_minutes` from `meta.json` and `overall_score`
from `grading.json` — no dependency on `report.json`. Size limits: 200 MB request body, 100 MB
per session, 20 MB per file. GitHub submissions tracked in `/data/github_submissions.json`.

### `interview/dashboard/serve.py`
Local HM dashboard at `http://localhost:7832`. Transport-aware: in relay mode reads from and
writes to relay; in email mode reads from `~/.interview/received/`. Routes: candidate list,
candidate detail, grade, comment, decision, audit, sharing panel, integrity verify. `_ensure_local_cache()` downloads `events.jsonl` and `manifest.json` from the relay to the local
sessions directory so `grader.py` (which reads local files) can work normally. All responses
carry `Cache-Control: no-store` to ensure fresh data on refresh.

**First-run setup wizard.** On launch, `_is_config_complete()` checks for `relay_url` and
`anthropic_api_key`. If either is missing, the dashboard shows a 3-screen wizard: (1) relay URL
entry with https:// validation, (2) Anthropic API key, (3) Create Interview form. Subsequent
launches skip the wizard and land directly on the candidate list. `+ Create Interview` in the
topbar is always available for additional interviews.

**Interview code selector.** `GET /` accepts a `?filter=<code>` param. The candidate list
defaults to the most recently created interview code and renders pill tabs for switching between
codes. `_build_dashboard_html(reports, all_codes, current_code)` builds the selector.

**Transcript rendering.** `_render_transcript_html(events, manifest)` builds the full terminal
experience from the event log. Preamble boundary: only the `session_start` event (and its
immediate `tool_result`, if any) are collapsed into "Session setup" — all other pre-user-prompt
events stay in `conv_events` where the `pending_tools` buffer attaches them to the correct turn.
`_strip_session_banner()` strips the session banner prefix from assistant messages, showing any
content that follows the last ━━━ line.

Candidate list reads `manifest.json` + `grading.json` per session — no dependency on
`report.json`.

### `interview/skills/interview/SKILL.md`
The Claude Code skill file for `/interview`. Candidate-only — HM setup has moved to the
dashboard browser wizard. Step 0 detects relay mode. Candidate flow: asks name + email, calls
`python -m interview.core.session start`, shows the problem statement. Typing `/interview hm`
redirects to `interview dashboard`.

### `interview/skills/submit/SKILL.md`
The Claude Code skill file for `/submit`. Five steps: (1) check active session, (2) seal via
`python -m interview.core.session seal`, (3) generate report + send via transport, (4) fetch
score if `auto_graded: true`, (5) show result block. Debrief generation is not part of the flow —
candidates see overall score + 1-line summary only. Full dimension breakdown is HM-only in the
dashboard.

---

## Key architectural facts

**record_reveal() is a no-op.** Identity is always visible. `decisions.record_reveal()` and
`store.record_reveal()` both return immediately without mutating state. The Reveal button was
removed from the dashboard. The function is kept only for API and code compatibility.

**Dashboard is transport-aware.** `serve.py` calls `get_transport()` on every request. In relay
mode all reads and writes go through `RelayTransport`. In email mode they go through `EmailTransport`
which reads from `~/.interview/received/` and local session files.

**Grade-before-reveal enforcement is removed.** The relay's `POST /sessions/{code}/{cid}/reveal`
endpoint still exists for compatibility, but is a no-op — it returns 200 and does nothing. The
server does not check `is_graded` before processing reveal.

**Grading is HM-only.** The `/submit` flow seals, reports, and sends. It never calls
`grade_session()`. Grading happens when the HM clicks "Grade" in the dashboard.

**Multi-tenant relay is the current implementation.** Each HM registers via `POST /register`
and receives a unique `hm_key`. Sessions, interviews, and sharing configs are all namespaced
under `/data/hms/<hm_key>/`. No HM can see another's data.

**GitHub OAuth.** Relay validates one-account-one-submission at both `GET /auth/github/callback`
(early warning) and `POST /sessions` (hard enforcement). On OAuth success, the relay stores
`github_id`, `github_username`, `avatar_url` in `meta.json`. The GitHub access token is
returned to the candidate CLI via the poll endpoint but never written to `manifest.json` or
stored on the relay.

**Git repo lifecycle.** At session start, `session.py` calls `_ensure_git_init()` (creates a
repo if needed, makes an initial commit), then `_create_github_repo()` via the GitHub API, then
wires up the `interview` remote. On `/submit`, `seal_session()` calls `_git_push_session()`,
which embeds the token in the remote URL for the push and clears it immediately after. All git
and API operations are wrapped in `try/except` — failure is non-blocking.

**Debrief removed from /submit.** Claude no longer generates `debrief.txt` at submit time.
The Read tool permission prompt during `/submit` created a tamper vector (candidate could deny
it). Candidates now see overall score + 1-line summary from `interview score`. Full dimension
breakdown and the analysis panel are HM-only in the dashboard. The relay still accepts
`debrief.txt` uploads for backwards compatibility.

**Setup wizard is first-run only.** `_is_config_complete()` checks for `relay_url` +
`anthropic_api_key` on every dashboard launch. Once both are set the wizard never shows again.
Config is stored in `~/.interview/config.json` (permissions: 600).

**Flags run at submit time.** `flags.compute_flags(events, manifest)` is called during the
relay's `POST /sessions` handler and the result is written to `flags.json` alongside the session
files. Dashboard reads flags from the relay session summary and displays them as colored badges.

**Hash chain.** Every event in `events.jsonl` stores `prev_hash` and `hash`, where
`hash = sha256(prev_hash + json(body))[:16]`. The first event has `prev_hash = ""`. The relay
also maintains a per-session `audit.jsonl` with the same chaining scheme for HM actions.
`integrity.py` re-derives every hash and cross-checks `manifest.final_hash`.

**Stop hook reads conversation logs.** `handle_stop()` in `claude_hook.py` searches
`~/.claude/projects/*/conversations/<session_id>.jsonl` for new user and assistant messages
since the last Stop, then logs them as `user_prompt` and `assistant_message` events. This is
the primary mechanism for capturing what the candidate actually typed.

---

## Data flows

### HM creates interview → relay → candidate fetches

```
interview dashboard  (first run: setup wizard → relay URL → API key → create interview form)
  → setup.create_interview(problem, rubric, time_limit_minutes)
    → generates code INT-XXXX-XX
    → embeds relay_url + hm_key in payload
    → stores ~/.interview/created/<code>.json
    → RelayTransport.push_interview()  →  POST /interviews (relay stores <code>.json)

Candidate runs /interview <CODE>
  → setup.load_interview(code)
    → RelayTransport.get_interview(code)  →  GET /interviews/<code>  (open, no auth)
  → session.start_session()
    → relay auto-configured from package (no candidate setup needed)
    → GitHub OAuth flow (if relay has GitHub app configured)
    → git init + initial commit + GitHub repo created + 'interview' remote wired
    → active_session.json written
    → session_start event logged
```

### Candidate /submit → seal → git push → relay → score

```
/submit
  → session.seal_session()
    → _git_push_session()  (commit all changes, push to GitHub, clear token)
    → captures git diff
    → writes manifest.json (final_hash, elapsed_minutes, etc.)
    → clears active_session.json
  → report.generate_report()  →  writes report.html + report.json  (local only; email attachments)
  → RelayTransport.send()
    → base64-encodes manifest + events  (report files NOT sent to relay; no debrief.txt)
    → POST /sessions  (relay creates <cid>/ directory, writes files, runs flags, writes meta.json)
  → if auto_graded: interview score <CODE>  →  candidate sees overall score + summary
```

### HM grades from dashboard → relay stores grade → candidate fetches score

```
interview dashboard  →  serve.py at localhost:7832
  → _load_all_reports()  →  RelayTransport.list_sessions()  →  GET /sessions
  → HM clicks Grade:
      _ensure_local_cache(code, cid)  →  downloads events + manifest locally
      grader.grade_session(code)      →  calls Anthropic API, returns grading dict
      transport.post_action('grade')  →  POST /sessions/{code}/{cid}/grade  →  relay writes grading.json
  → HM clicks Comment:
      transport.post_action('comment')  →  POST /sessions/{code}/{cid}/comment
  → HM clicks Decision:
      transport.post_action('decision')  →  POST /sessions/{code}/{cid}/decision

Candidate checks score:
  interview score <CODE>
    →  GET /sessions/{code}/{cid}/score  (open route, filtered by sharing config)
```

---

## Non-goals

- **Real-time monitoring.** The HM sees the full session only after submission. Real-time would
  change candidate behaviour.
- **File contents in event log.** Events record file paths and content hashes, not raw content.
  The git diff provides the reviewable code snapshot.
- **AI feedback loop from hire decisions.** Too noisy (budget, team fit, reference checks).
  The rubric is the calibration tool.
- **Relay is now required for multi-candidate workflows.** Email mode is a single-candidate
  fallback. A hosted relay (`relay.interviewsignal.dev` or self-hosted) is required to collect
  and rank submissions from multiple candidates.

---

## Adding a new platform

Each platform is a ~30-line function in `cli.py`:

1. Add an entry to `PLATFORMS` dict with install paths.
2. Write `_install_<platform>(verbose=True)` that copies SKILL.md and wires up
   `interview.hooks.claude_hook pre/post/stop` as the platform's hook equivalents.
3. Add the platform to `cmd_install()` dispatch and CLI argument choices.

The hook protocol varies by platform, but the core logic in `claude_hook.py` reads from stdin
and writes to stdout and can be adapted to any stdin/stdout-based hook system.

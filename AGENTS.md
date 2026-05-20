# interviewsignal — Codex conventions

## What this project is
AI-native broad-interviewing platform. One code, any number of candidates, pure signal.
Captures candidate thought process via AI coding assistant hooks. Auto-grades on submission. HM triages via dashboard.
pip installable, zero setup cost, completely secure. Primary audience: startups doing high-volume screening.
See README.md for the full pitch. See ARCHITECTURE.md for module responsibilities.

## Constraints (always enforce)
- Zero external dependencies for core — stdlib only (urllib, smtplib, http.server, hashlib)
- `anthropic` package is optional — grader.py calls the API via urllib directly
- Python 3.10+ — no f-string backslashes, extract to variables first
- All file writes atomic: write to .tmp then rename (see store.py for pattern)
- Hash chain integrity: every event has prev_hash + hash — never write events without chaining

## Key decisions (don't relitigate)
- Grading is HM-only — removed from /submit to prevent candidate manipulation
- Transport abstraction in core/transport.py — use get_transport() everywhere, never SMTP directly
- Relay over email for teams — relay server in interview/relay/
- No AI feedback loop from hire decisions — rubric is the calibration tool
- One repo — security from hash chain + HM-side grading, not code obscurity
- configure-github-app is relay operator only — hidden from `interview --help` (argparse.SUPPRESS); HMs never run it, relay operators set GITHUB_CLIENT_ID/SECRET/RELAY_BASE_URL directly in Railway Variables
- GitHub OAuth is candidate-side only — HM has nothing to configure per-interview; without OAuth candidates fall back to email identity
- Email questions (HM email, CC, candidate email, audit email) are skipped in relay mode — SKILL.md Step 0 detects relay via get_relay_url() before asking; setup.py --hm-email is optional (default "")
- Debrief removed from /submit — debrief generation (Read events.jsonl + Write debrief.txt) removed to eliminate the Read tool permission prompt during candidate submit; candidates see overall score + 1-line summary only; full dimension breakdown + analysis is HM-only in dashboard; debrief.txt is still uploaded if present (relay accepts it for backwards compat) but new sessions won't have it; sharing config is {"score": "none"|"overall"|"breakdown"|"breakdown_notes"}
- Client is untrusted — candidates can modify ~/.Codex/settings.json permissions or hooks since they own their machine. Security model is detection not prevention: flags.py detects tamper signals (hooks_gap, diff_event_mismatch, prompt_event_ratio) and surfaces them in the dashboard. Absence of signal IS signal — a sparse or gapped session is its own red flag.
- Don't nerf Codex during interviews — candidates work with full-power AI (that's the pitch: "work the way you actually work"). The grading prompt in grader.py explicitly calibrates for AI-dependence: high-leverage use (candidate outlines approach, directs AI, verifies output) scores well; low-leverage use (candidate throws problem at AI, accepts answer, says "yes") scores poorly. The transcript captures who drove the thinking — that's the signal, not whether Codex helped.
- Grade mutability with revision tracking — first grade is free; subsequent grades require a `reason` field, previous grade is archived to `grading_history.jsonl`, audit records `grade_revised` with `previous_score`, `new_score`, `reason`, and `revealed` (whether identity was known); dashboard shows revision badges and expandable history
- Per-prompt git commits — Stop hook silently runs `git add -A && git commit` after each user_prompt event (only when files changed). Commit message is timestamp + truncated prompt. On /submit, full commit history is pushed to the interview-{code} repo. seal_session() extracts commit log (hash, timestamp, message, files_changed) into manifest.json as `commit_log`. This gives: (a) step-by-step code evolution visible in GitHub, (b) independent verification source for cross-checking against events.jsonl, (c) richer grading context than a single start-to-end diff. Commits are non-blocking: subprocess with 2-second timeout, failure is silent. Only commit when `git diff --quiet` fails (actual changes exist).
- Automatic cross-verification in flags.py — `_flag_commit_event_mismatch` compares commit_log timestamps/files against tool_call events. Commits with no matching Write/Edit events = candidate worked outside AI assistant. Write/Edit events with no matching commits = silent commits were disabled. Both directions are flags. HM never manually compares — flags surface mismatches automatically; GitHub repo link is available for manual inspection if needed.
- GitHub repo creation is candidate-side and non-blocking — created at session start via GitHub API token from OAuth; pushed on submit; repo URL flows to relay and is shown in HM dashboard; token never written to manifest.json; all git/API ops wrapped in try/except
- Identity always visible — grade-before-reveal gate removed; dashboard always shows candidate name, email, GitHub username, avatar, repo link; record_reveal() is a no-op kept for compat
- HM experience is 100% browser — `interview dashboard` is the only command an HM runs; first launch shows setup wizard (relay, API key), then "Create Interview" form replaces `/interview hm`; `/interview hm` skill removed; setup.py create_interview() called from dashboard HTTP handler, not CLI
- Candidate experience is 100% terminal — `/interview CODE` in Codex, Codex, Cursor, Gemini CLI, or Aider; candidates never need a browser
- Multi-platform support — `interview install --platform {Codex,codex,cursor,gemini,aider}`. Codex and Codex have full hook support (PreToolUse/PostToolUse/Stop). Gemini CLI has native hooks via `.gemini/settings.json`. Cursor and Aider get skill instructions only (`.cursorrules` / `CONVENTIONS.md` + `.aider.conf.yml`) — no lifecycle hooks, activity capture is limited. All adapters are idempotent.
- First-run setup wizard in dashboard — detects missing config, walks HM through relay + API key + first interview creation in 3 screens; replaces configure-relay and configure-api-key CLI commands for HMs
- HM setup is 3 fields in dashboard form — problem, rubric, time limit; anonymize hardcoded False, sharing hardcoded {"score":"overall"}, auto_grade hardcoded True; setup.py accepts --problem/--rubric as direct string args; relay auto-configured from package on candidate side
- Candidate identity collected at session start — skill asks name + email before session start; passed as --candidate-name/--candidate-email; GitHub identity (from OAuth) takes priority if available
- interview install writes permissions — Read/Write for ~/.interview/*, all python -m interview.core.* variants, git commands; uses Path.home() + sys.executable so paths are correct per-user
- report.json/report.html are local-only artifacts — generated for email attachments but never uploaded to relay; dashboard reads candidate list from manifest.json + grading.json; transcript view is the canonical HM view (not report.html)
- hm_key never reaches candidate machines — `GET /interviews/<code>` returns a candidate-safe package (problem, time_limit, relay_url, submit_token) via `candidate_package()` in setup.py; rubric and hm_key are stripped server-side. `_CANDIDATE_SAFE_FIELDS` in store.py is the authoritative whitelist.
- submit_token is scoped per interview code — generated with `secrets.token_urlsafe(32)` at interview creation time; stored in the interview package on the relay; flows HM → relay → candidate package → session manifest → submission body. `POST /sessions` accepts either HM Bearer token or submit_token in the request body; `hmac.compare_digest` for constant-time comparison. A compromised submit_token grants write-only access to one interview code — no read access to other candidates, no rubric, no hm_key. `_ensure_submit_token()` in store.py auto-generates a token for pre-fix packages on first access (backward compat).

## Framing (preserve in all user-facing copy)
- "Broad-interviewing" not "mass hiring" — broadcasting one signal to many candidates, both sides benefit
- "Zero setup cost" — pip install, share a code, done. No platform, no vendor, no procurement
- "Fair shot for every candidate" — same problem, same tools, real feedback. Not a black box.
- The audit trail proves the sequence, it doesn't just log it
- Primary audience is startups doing high-volume screening; enterprise is secondary
- The rubric NEVER leaves the relay — candidates see the problem, not the grading criteria
- "AI-graded take-home assessment" is the gateway framing that people connect to immediately, but it dilutes the scope. The differentiator is capturing the THOUGHT PROCESS, not just grading the output. Keep the pitch focused on broad-interviewing — the take-home framing opens the door, the thought process capture closes it.
- Differentiator vs ATS grading partners (Greenhouse, Lever, Ashby) — they grade the output (did the code pass tests). We grade the thinking (how did the candidate decompose the problem, direct the AI, iterate on failures). When every candidate uses AI and output quality converges, thought process is the only remaining signal. ATS partners validate the market; we capture a signal they can't because they don't sit inside the candidate's working session.

## Commands
```bash
# HM (all browser-based after first command)
pip install interviewsignal         # install
interview dashboard                 # first run: setup wizard → create interview; subsequent: dashboard
interview dashboard <CODE>          # open dashboard straight to a candidate

# Candidate (all terminal-based)
pip install interviewsignal && interview install                    # Codex (default)
pip install interviewsignal && interview install --platform codex   # Codex
pip install interviewsignal && interview install --platform cursor  # Cursor
pip install interviewsignal && interview install --platform gemini  # Gemini CLI
pip install interviewsignal && interview install --platform aider   # Aider
/interview <CODE>                   # start session
/submit                             # seal + relay upload + show score summary

# Relay operator
python -m interview.relay.server    # run relay server directly
docker compose up                   # run relay via Docker

# Dev
pip install -e .                    # install locally (editable)
```

## What's next
Priority: worked examples (worked/calculator/, worked/titanic/) → self-hosting docs → problem library.
Upcoming: Grade All batch action.

## Roadmap (post-feedback)

**Multi-stage pipelines.**
Right now it's one code, one problem, one round. The natural next step: a pipeline. Screening round (easy problem, auto-grade, auto-advance top 30%) → technical deep dive (harder problem, HM reviews top candidates) → system design (open-ended, HM grades manually). The HM defines the pipeline once. Candidates who pass each stage automatically get the next code. The HM only touches the final round.

**Problem library.**
Every HM writes their own problem and rubric from scratch right now. What if there was a community library of vetted problems with calibrated rubrics? "Rate limiter — senior backend — 90 min" with a rubric that's been tested on 200 candidates and tuned. HMs pick a problem, customize the rubric, deploy. This becomes a marketplace.

**Non-coding roles.**
The mechanism works for anything where the candidate works with an AI tool and you can define what "good" looks like. Data analysis: here's a dataset, find insights. Product: write a PRD for this feature. Technical writing: document this API. The capture is the same (prompts, tool calls, outputs), the rubric changes.

**ATS integration.**
Greenhouse, Lever, Ashby — recruiters live there. The recruiter tags 100 candidates in the ATS, clicks "Send interviewsignal," the code goes out. Results flow back into the ATS as scores. The HM never leaves their existing workflow. This is where the enterprise money is, but it's also where the sales cycle gets long.

**Calibration over time.**
Explicitly deferred the AI feedback loop from hire decisions — the signal from "HM hired the 7 over the 10" is too noisy. But at scale with a problem library, there's enough data: if the rubric consistently scores candidates that HMs reject, the rubric is miscalibrated. Not individual feedback, but rubric-level calibration across many HMs using the same problem.

**NOTE:** All of the above is deferred until we have real user feedback. Get 3-5 startups to actually run interviews with the product first, then revisit.

## assignmentsignal — sister product for education

**Same mechanism, separate product.** Universities and colleges face the same problem: students use AI for assignments and professors can't tell who thought vs who copy-pasted. assignmentsignal captures the thought process the same way interviewsignal does — hooks, hash-chained event logs, rubric-based grading, dashboard for review.

**Separate repo, separate PyPI package, separate identity.** `pip install assignmentsignal` → `assignment install` → `/assignment` skill. Forked from interviewsignal, then diverges independently based on education-specific demand. Separate repos let each product evolve without coordinating releases.

**Why separate, not a mode flag:**
- Different discovery paths — professors searching "AI assignment integrity" won't find interviewsignal
- Different pitch narratives for different audiences (startups vs universities)
- Products will diverge: assignmentsignal needs LMS integration (Canvas, Blackboard, Moodle), group projects, department hierarchies, TA workflows, deadline-based timing (days not hours), grade-back-to-gradebook. interviewsignal needs ATS integration (Greenhouse, Lever), job matching, multi-stage pipelines, problem banks.
- Can pitch separately to Anthropic — education team vs enterprise team

**Education-specific features (post-fork):**
- LMS integration: grades flow back to Canvas/Blackboard gradebook via LTI
- University SSO/CAS for identity instead of GitHub OAuth
- Group submissions: multiple students, one code, shared event log
- TA role: TAs triage and grade, professor reviews
- Department hierarchy: CS dept config differs from Math dept, same relay
- Resubmission: students can resubmit (interviews are one-shot)
- Score sharing defaults to breakdown (students need feedback to learn)

**Validated feedback (2026-04-25 — conversations with UGA PhD TA and Texas 2-year college friend):**
- 2-year colleges move faster than universities — less bureaucracy, actively want AI tools, zero setup cost is the hook. Target 2-year colleges first, universities second.
- OAuth and relay must be configurable per-institution — college IT sets up their own relay and identity provider (university SSO, institutional email, not just GitHub OAuth). The package is the platform; each institution configures it.
- No "hire/no hire" — the decision model doesn't apply to education. Reimagine as: TA reviews, adjusts score, finalizes. No binary decision gate.
- Score NEVER shown to student at /submit — only qualitative feedback (debrief). Auto-grade runs but is TA-only (a suggestion, not the student's grade). Student sees score only after TA finalizes. Reason: if student sees AI score of 88% and TA gives 72%, TA spends the semester defending the gap. The AI grade is a starting point for the TA, not a promise to the student.
- TA workflow: open dashboard → 150 submissions pre-sorted by AI suggestion score → spot-check top and bottom → adjust where needed → finalize. 15 minutes instead of 15 hours.
- The debrief (qualitative feedback) CAN reference the professor's rubric criteria since students typically know grading criteria upfront in education (unlike hiring where rubric is hidden from candidates).

**The pipeline vision (Anthropic pitch):**
assignmentsignal captures how students learn and work with AI throughout university. When they graduate and job-hunt, interviewsignal captures how they solve real problems. The full lifecycle — education → job discovery → hiring → onboarding — runs through Codex. Candidate asks Codex "what PM roles match my skills?" → Codex matches JDs → candidate applies → HM's AI filters resumes against JD → HM sends interview code or rejects → interviewsignal workflow begins → auto-graded, ranked, hired. Both products make Codex the connective tissue across the talent pipeline.

**Validation plan:** Friend teaches at a 2-year tech college in Texas (faster adoption, wants AI tools). Friend is a PhD TA at University of Georgia (slower adoption, but prestigious proof point). Get both to try interviewsignal as-is for an assignment. Their feedback informs what actually needs to change for the fork.

**Timing:** Fork after interviewsignal is validated with 3-5 startups. The education product follows demand, not speculation. 2-year colleges are the beachhead for education — universities follow.

## Prompt files (community-editable)
The full interview skill prompt is in `interview/skills/interview/SKILL.md`.
`prompts/debrief.md` exists but debrief generation was removed from /submit in v0.9.2 — file is kept for reference only.

## Recently shipped (0.9.15)
- Edit Rubric panel in dashboard: collapsible "▸ Edit Rubric" below interview code tabs; textarea pre-filled with current rubric from local created/ file; Save updates both local file and relay via `POST /interviews/{code}/rubric`; success message prompts HM to select candidates and Regrade to apply. Relay store adds `update_rubric()` method.

## Recently shipped (0.9.14)
- Per-session events cleanup: `start_session()` now archives stale `events.jsonl`, `manifest.json`, and `grading.json` (renamed with timestamp suffix) before writing the first event. Fixes bug where running the same interview code twice on one machine (e.g., testing as two candidates) appended events from both sessions into one file, causing the grader to average both candidates' work together.

## Recently shipped (0.9.13)
- Attribution-based grading: grading prompt now includes an ATTRIBUTION RULE — score each rubric dimension based on what the CANDIDATE demonstrably contributed in the transcript, not what the AI produced in the output. Great code produced by the AI is the AI's achievement, not the candidate's.
- Regrade batch action in dashboard: "↻ Regrade" (indigo) in the batch action bar — select candidates, click regrade, each one gets fresh AI grading via `/regrade` endpoint (clears local cache, re-runs `grade_session`, posts to relay as revision with reason "AI regrade requested by hiring manager"). Sequential with progress indicator. Distinct from "Revise Grade" (amber) on detail page which is manual score override.
- Grader CLI guard: `interview grade` checks for `~/.interview/created/{code}.json` — only the HM who created the interview can grade locally. Candidates cannot run the grader.
- Detail page width fix: `grid-template-columns: minmax(0, 1fr) 340px`, `min-width: 0` on grid children, `overflow-wrap: break-word` on transcript — no more horizontal scroll on the detail page.
- Rubric hint in Create Interview form: "Your rubric dimensions are your weights. If you want thought process to matter more than code quality, make more of your dimensions about process." shown below rubric textarea.

## Recently shipped (0.9.11)
- Decision labels changed: hire/next_round/reject → yes/maybe/no across decisions.py, dashboard buttons, batch actions, detail page, and summary bar
- Decision column added to candidate list table — shows ✓ Yes / → Maybe / ✗ No / — inline per row
- Summary bar: "advancing/rejected" replaced with yes/maybe/no counts (colored green/indigo/red); counted from data-decision attribute, not badge text scraping

## Recently shipped (0.9.10)
- `/interview` flow is now fully deterministic: `interview install` prompts for name + email once, stores in `~/.interview/config.json`; `session start` reads from config (GitHub > args > config > package). SKILL.md reduced to one command — no LLM-driven identity collection.
- Auto badge clears on grade revision: `/revise-grade` now sets `graded_by: "hm"` explicitly, overwriting the auto-grade value. Previously the badge stayed "Auto" after manual revision.
- Git commit messages in Stop hook expanded from 60 to 120 chars — full prompt text visible in commit history.

## Recently shipped (0.9.6)
- Security fix: `hm_key` was in `_CANDIDATE_SAFE_FIELDS` — any candidate could read the HM's admin credential from `GET /interviews/<code>` and use it to read other candidates' sessions, access the rubric, or submit fake sessions. Fixed by removing `hm_key` from candidate-facing responses entirely.
- Per-interview `submit_token` (`secrets.token_urlsafe(32)`) replaces hm_key for candidate submissions — scoped to one interview code, write-only, no read access. Generated at interview creation, stored on relay, flows through the package to the candidate's session manifest.
- `POST /sessions` is now an open route — accepts HM Bearer token OR submit_token in request body; `hmac.compare_digest` prevents timing attacks.
- `_ensure_submit_token()` in store.py: backward-compat migration generates a token for pre-fix interview packages on first access.
- `candidate_package()` helper in setup.py: explicit whitelist of candidate-safe fields, used for both relay push and offline token generation.
- Fixed Python indentation bug in `_write_relay_config` (session.py): `except Exception` was at function-body level instead of inside the `if` block — introduced as a merge artifact.

## Recently shipped (0.9.5)
- Dashboard visual redesign: new design system — zinc color scale (#0a0a0b through #a1a1aa), indigo accent (#4f46e5/#818cf8), Inter + JetBrains Mono typography, 12px rounded panels, gradient stat card borders, score rings (42px bordered circles), avatar initials on candidate rows
- Detail page redesign: transcript uses JetBrains Mono with subtle border, dimension score bars 4px with transitions, dark-mode flag badges (#1c0a0a red / #1c1508yellow), indigo auto-graded badges, all form inputs use indigo focus states, verify chain results use monospace numbers
- CSV export: "↓ Export CSV" button in toolbar, client-side Blob download of filtered candidates (Candidate, Score, Flags, Duration, Events, Decision columns)
- Full palette cleanup: zero instances of old colors (#888, #555, #333, #1a1a1a, #60a5fa) remain — every color maps to zinc scale, indigo accent, or semantic colors
- Dashboard key decision: design system is inline in serve.py (not extracted to separate CSS file) — the value is visual polish, not refactoring; surgical edits to the 2,500-line file, not restructuring

## Recently shipped (0.9.4)
- Multi-platform adapters: `interview install --platform {cursor,gemini,aider}` alongside existing Codex/codex. Cursor gets `.cursorrules`, Gemini CLI gets `GEMINI.md` + `.gemini/settings.json` with hooks, Aider gets `CONVENTIONS.md` + `.aider.conf.yml` with `read:` directive. All idempotent. Cursor and Aider warn that activity capture is limited without lifecycle hooks.
- Test suite expanded: test_flags.py (15 tests covering all 9 flag detectors — too_fast, few_interactions, no_iteration, uniform_timing, no_prompts, hooks_gap, diff_event_mismatch, prompt_event_ratio, commit_event_mismatch), test_grader.py (14 tests covering transcript builder, tool summarizers, API key resolution including enterprise proxy path). Total: 4 test files.
- Per-prompt git commits and commit cross-verification flag verified end-to-end (implemented in 0.9.3, tested in 0.9.4)

## Recently shipped (0.9.3)
- Tamper detection flags in flags.py: hooks_gap (large gaps in event stream suggest hooks disabled mid-session), diff_event_mismatch (git diff line count vs Write/Edit tool calls — catches work done outside AI assistant), prompt_event_ratio (tool calls with no corresponding user prompts — catches selective hook suppression)
- Security model codified: client is untrusted, detection not prevention; absence of signal is signal

## Recently shipped (0.9.2)
- Dashboard: interview code selector tabs above stats; defaults to most recent code on load; click to filter by any code
- Transcript: preamble partition fixed — only `session_start` event belongs in collapsed "Session setup"; working-turn tool calls (PreToolUse fires before Stop hook logs user_prompt) now correctly appear in their turn via pending_tools buffer
- Transcript: `_strip_session_banner` replaces `_is_session_banner` — assistant messages containing the session banner now show content after the last ━━━ line instead of being suppressed entirely
- /submit skill: debrief generation removed (eliminates Read tool permission prompt during candidate submit); candidates see overall score + 1-line summary only
- `interview score`: strips dimensions/debrief from output; candidates see score + summary only; full breakdown stays in HM dashboard
- Wizard step 1: inline error "Enter a valid URL starting with https://" on invalid relay URL

## Recently shipped (0.9.0)
- Dashboard as HM product: first-run setup wizard (3 screens: relay → API key → create interview) replaces CLI configure-relay/configure-api-key for HMs
- Create Interview form in browser: problem, rubric, time limit — anonymize hardcoded False, sharing hardcoded overall, auto_grade hardcoded True
- `+ Create Interview` button in dashboard topbar for repeat use
- `/interview hm` skill removed — interview creation is now browser-only

## Recently shipped (0.8.5)
- HM setup reduced to 3 questions (problem, rubric, time limit); anonymize/sharing/auto_grade hardcoded (False / {"score":"overall"} / True)
- Codex's Analysis panel in HM dashboard: rubric-based grading shown below transcript (summary, per-dimension scores with color bars, standout moments, concerns); HM-only view
- Git diff expanded by default in transcript — `<details open>`
- Debrief removed from HM transcript view (still sent to candidate at submit)
- Event grouping fix: pending_tools buffer correctly attaches tool calls to the user prompt that triggered them (Pre/PostToolUse hooks fire before Stop hook logs user_prompt)

## Recently shipped (0.8.3)
- Full terminal transcript: synthesized pre-session preamble (❯ /interview CODE, name/email exchange, session banner + problem) prepended to events; session debrief shown at bottom after submission block
- report.json and report.html removed from relay upload — relay stores events + manifest + debrief only; report files remain generated locally for email attachments
- Dashboard candidate list (local mode) reads elapsed_minutes/overall_score from manifest.json + grading.json — no longer depends on report.json
- store.py _summarise_candidates() reads elapsed_minutes from meta.json, overall_score from grading.json; get_session() now includes debrief field
- "View generated report →" link removed from dashboard transcript panel (transcript is the report now)
- Key constraint: report.json/report.html must never be added back to relay upload; the transcript view in the dashboard is canonical

## Recently shipped (0.8.2)
- Terminal transcript view in HM dashboard: problem at top, setup collapsed, GitHub-style diffs for Write/Edit, identity panel top-left

## Recently shipped (0.6.0)
- Identity always visible: removed grade-before-reveal gate; dashboard always shows name/email/GitHub/avatar; record_reveal() is a no-op
- HM setup is 5 questions: problem, rubric, time limit, anonymize (default no), score sharing (default none); setup.py accepts --problem/--rubric string args directly (no echo temp files)
- interview install writes Codex permissions: Read/Write ~/.interview/*, all python -m interview.core.* variants, git commands — no more yes/no prompts during interview flow
- dashboard <CODE>: opens directly to a candidate's detail page
- Cache-Control: no-store on all dashboard responses — always fresh data on refresh
- BrokenPipeError silenced in dashboard send helpers (harmless browser disconnect noise)

## Previously shipped (0.4.0)
- Mutable grades with revision tracking: grading_history.jsonl archives superseded grades; grade_revised audit event with revealed field (identity known at revision time); dashboard revision badges, Revise Grade form, expandable history
- GitHub repo auto-creation: created at session start via GitHub API (access token from OAuth poll); git remote `interview` wired up; code pushed on /submit (non-blocking); github_repo_url flows to relay and shown in HM dashboard
- Anonymize default off: changed from True to False across setup.py, session.py, transport.py, SKILL.md
- Sharing config simplified: removed debrief/hm_notes toggles; sharing is {"score": "none"|"overall"|"breakdown"|"breakdown_notes"} only; debrief always shared automatically

## Previously shipped (0.3.0)
- Session debrief: after /submit Codex reads events.jsonl and writes debrief.txt — focused reflection on what candidate did well, missed, AI usage quality; shown immediately in terminal; included in relay submission
- Candidate score sharing: HM sets score sharing level at interview creation (none/overall/breakdown/breakdown_notes); mutable from dashboard sharing panel; debrief always included automatically
- GET /sessions/{code}/{cid}/score relay endpoint — open route, response filtered by sharing config
- POST /sessions/{code}/sharing relay endpoint — HM updates sharing config, audit-logged
- interview score <CODE> CLI command — fetches candidate's own score from relay using cid from manifest
- Dashboard sharing panel: per-interview toggles on candidate detail page (relay mode only)

## Previously shipped (0.2.0)
- GitHub OAuth: one GitHub account = one submission per interview code, relay-enforced

## Imported Claude Cowork project instructions

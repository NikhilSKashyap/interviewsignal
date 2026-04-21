# interviewsignal

[![PyPI](https://img.shields.io/pypi/v/interviewsignal)](https://pypi.org/project/interviewsignal/)
[![Downloads](https://static.pepy.tech/badge/interviewsignal/month)](https://pepy.tech/project/interviewsignal)
[![GitHub](https://img.shields.io/badge/github-NikhilSKashyap%2Finterviewsignal-blue)](https://github.com/NikhilSKashyap/interviewsignal)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Broad-interview, not broadcast-reject.** One code. Any number of candidates. Every one of them gets a fair shot — real problem, real tools, real feedback. `pip install` and you're running. Zero setup cost. Completely secure.

No contrived puzzles. No whiteboard anxiety. Just signal.

---

## What is broad-interviewing?

The same way broadcasting reaches many listeners with one signal, broad-interviewing reaches many candidates with one interview. Share a code, and every candidate works the problem on their own time, with their own AI tools, on a real problem. You get back structured, graded, ranked results. They get back honest feedback. Both sides win.

```
Create interview  →  Share code  →  Candidates work  →  Auto-grade  →  Triage  →  Hire
```

**For the startup:** you posted a role and got 200 applications. You can't interview all of them live. With interviewsignal, you share one code, submissions arrive auto-graded and ranked, you spend 15 minutes triaging — advance the top 10, reject the rest, done.

**For the candidate:** no scheduling, no whiteboard, no trick questions. You work the way you actually work — with AI assistance, on your own time. You get a session debrief from Claude immediately and your score once the HM grades. Every candidate gets the same shot regardless of timezone, schedule, or interview anxiety.

**For everyone:** `pip install interviewsignal && interview install`. That's the entire setup. No platform to sign up for. No vendor contract. No procurement cycle. No setup cost.

---

## Install

```bash
pip install interviewsignal && interview install
```

Requires Python 3.10+ and [Claude Code](https://claude.ai/code) or [Codex](https://openai.com/codex).

```bash
interview configure-api-key    # Anthropic API key — for grading
interview configure-relay      # relay URL — auto-registers your HM account
```

> **Enterprise / no personal API key?** See [Enterprise configuration](#enterprise-configuration) below.

---

## Quickstart

### Hiring manager

```
/interview hm
```

You'll be asked for:
- Problem statement
- Grading rubric (plain language — "weight decomposition 40%, code quality 30%, tests 30%")
- Time limit (optional)
- Anonymize candidates? (default: no — candidates appear by name; yes shows "Candidate A/B/C" until you unmask)
- Score sharing (default: none — what candidates see after grading: none / overall / breakdown / breakdown_notes)
- Auto-grade submissions? (default: no — requires `GRADING_API_KEY` on relay)

You get back a code like `INT-4829-XK`. That's your broad-interview — share it with 5 candidates or 500. They all get the same problem, they all get a fair shot, submissions arrive in your dashboard auto-graded and ranked.

### Candidate

```bash
pip install interviewsignal && interview install
/interview INT-4829-XK
```

You'll be asked for your name and email. If the relay has GitHub OAuth configured, a browser tab opens for login — one account, one submission — and GitHub identity takes priority. The problem appears once auth completes. A GitHub repo (`interview-{code}`) is created automatically and a git remote named `interview` is wired up in your working directory. Work normally — ask the AI questions, write code, run tests. The session records everything automatically.

When done:

```
/submit
```

The session is sealed, pushed to the relay, and Claude writes a session debrief — an honest reflection on what you did well, what you missed, and how you used the AI. It's shown in the terminal immediately. Once graded, you can also run:

```bash
interview score INT-4829-XK
```

to see your score (if the HM has enabled sharing).

### Hiring manager — review

```bash
interview dashboard              # → http://localhost:7832
interview dashboard INT-4829-XK  # → filter to one interview's submissions
```

Submissions arrive sorted by score. Flags highlight anomalies — sessions that were too fast, showed no iteration, or had suspiciously uniform timing. Select candidates in bulk and advance or reject in one click. Click into any candidate to see the full transcript, dimension scores, and diff. Add comments. Record your decision.

Use **Verify Chain** to confirm the session log is tamper-evident. Control what candidates see after grading with the **Score Sharing** panel. Claude's session debrief is always shared automatically regardless of this setting.

---

## How it works

interviewsignal installs as a skill into your AI coding assistant. It captures the full conversation — prompts, AI reasoning before each action, every tool call (reads, writes, bash commands) — and builds an append-only, hash-chained session log. On `/submit`, the log is sealed and pushed to the relay.

```
Candidate side                          HM side
─────────────────────────               ───────────────────────
                                        interview configure-relay
                                          ↓ gets unique hm_key

/interview hm                           ← share code INT-4829-XK
  ↓ creates interview
  ↓ pushes package to relay

/interview INT-4829-XK                  interview dashboard
  ↓ fetches problem from relay            ↓ localhost:7832
  ↓ relay auto-configured locally         ↓ submissions arrive, ranked
Session starts                            ↓ auto-graded (if enabled)
  ↓ hooks capture every tool call         ↓ flags highlight anomalies
  ↓ append-only events.jsonl              ↓ batch advance / reject
  ↓ hash chain (tamper-evident)           ↓ hire / next round / reject
/submit
  ↓ session sealed
  ↓ git push → interview-{code} repo
  ↓ pushed to relay
  ↓ Claude debrief written + shown
```

**On submit:**
1. `session seal` — finalises hash chain, captures git diff (start → end)
2. Git push — commits all changes to the candidate's `interview-{code}` repo (non-blocking)
3. Push to relay — sealed session (events + manifest + report + debrief + repo URL) stored server-side
4. Claude debrief — reads the event log, writes `debrief.txt`, shown to candidate immediately
5. Auto-grade — if enabled and `GRADING_API_KEY` is configured on relay, grade runs immediately

---

## Relay

The relay stores interview packages and candidate sessions so HMs and candidates only need to share a short code — no file transfers, no email attachments.

```bash
interview configure-relay
```

```
How do you want to deliver interview sessions?
──────────────────────────────────────────────
  1. Your own relay  Railway / Render / self-hosted — private, ~$5/mo
  2. Email only      SMTP — no server, reports arrive by email
```

### Option 1 — Your own relay (~$5/mo, fully private)

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/NikhilSKashyap/interviewsignal)

After deploying:
1. Set `RELAY_API_KEY` (any random string) in Railway → Variables
2. Add a `/data` volume — this is where sessions are stored
3. Copy your Railway URL (e.g. `https://myrelay.up.railway.app`)
4. Run `interview configure-relay` → option 1 → paste URL

Optional — auto-grading on submission:
```
GRADING_API_KEY=<anthropic-key>          # enables auto-grading
GRADING_MODEL=claude-haiku-4-5-20251001  # model to use (default)
```

Or with Docker:

```bash
docker build -t interviewsignal-relay .
docker run -e RELAY_API_KEY=secret -v /data:/data -p 8080:8080 interviewsignal-relay
```

#### GitHub OAuth

Prevent candidates from submitting multiple times under different names. One GitHub account = one submission per interview code.

This is a **relay operator** step — done once at deploy time, not something HMs configure per-interview.

Add to your relay's environment variables:
```
GITHUB_CLIENT_ID=<your_client_id>
GITHUB_CLIENT_SECRET=<your_client_secret>
RELAY_BASE_URL=https://myrelay.up.railway.app
```

Create the GitHub OAuth App at `github.com/settings/developers`:
- **Application name:** your company or team name
- **Callback URL:** `https://myrelay.up.railway.app/auth/github/callback`

When configured, candidates see a browser auth step at session start. The relay enforces uniqueness server-side. The HM sees the candidate's GitHub username, avatar, and a link to their session repo.

Without GitHub OAuth, candidates are identified by name + email.

See [docs/relay-api.md](docs/relay-api.md) for the full API contract and data layout.

### Option 2 — Email only (free, no server)

```bash
interview configure-relay   # choose 2
interview configure-email   # set up SMTP credentials
```

Reports are emailed directly to the HM on `/submit`. The HM saves the JSON attachment to `~/.interview/received/` and it appears in the dashboard.

---

## Why this works

Every candidate session is append-only and SHA-256 hash-chained — any tampering breaks the chain. In relay mode, the relay's server-side timestamp is the integrity anchor. Grade revisions require an explicit reason and the audit records whether identity was known at revision time:

```
[2026-04-13T10:47:22Z] grade_recorded  INT-4829-XK  hash=d4abe5e6  score=7.7
[2026-04-13T11:30:00Z] grade_revised   INT-4829-XK  hash=9f2c1a3b  7.7→8.2  reason="missed edge cases"
```

Use `GET /audit/verify` to walk the full chain and confirm integrity.

The session flags system detects common signal-noise issues: sessions completed in under 10 minutes (too fast), fewer than 3 tool calls (few interactions), no failed-then-fixed iteration pattern (no iteration), statistically uniform event timing (possible scripting), and zero prompts logged (no prompts). Flags appear as color-coded indicators in the dashboard — you decide what to do with them.

---

## Enterprise configuration

```bash
interview configure-llm
```

| Pattern | What to set |
|---|---|
| Anthropic direct | API key only (default) |
| Internal proxy (Floodgate, corporate gateway) | Base URL + optional key; proxy handles auth |
| OpenAI-compatible endpoint | Base URL + key + `format=openai` |

Config stored in `~/.interview/config.json`:

```json
{
  "anthropic_base_url":      "https://ai-gateway.corp.internal/anthropic",
  "anthropic_api_key":       "",
  "api_format":              "anthropic",
  "grading_model":           "claude-haiku-4-5-20251001",
  "anthropic_extra_headers": {"X-Team-ID": "ml-hiring"}
}
```

Environment variable overrides:

```bash
ANTHROPIC_API_KEY=...           # API key
ANTHROPIC_BASE_URL=...          # base URL override
INTERVIEW_GRADING_MODEL=...     # model name override
```

---

## Platform support

| Platform | Status | Install |
|---|---|---|
| Claude Code (Linux/Mac/Windows) | Supported | `interview install` |
| Codex | Supported | `interview install --platform codex` |
| Cursor | Coming soon | — |
| Gemini CLI | Coming soon | — |
| Aider | Coming soon | — |

---

## What gets captured

| Event | Captured |
|---|---|
| Candidate prompts | Exact message to the AI assistant |
| AI reasoning | Plan before each action ("I'll use a hash map because...") |
| File reads | Path |
| File writes | Path + content hash |
| Bash commands | Command + exit code |
| File edits | Path + change summary |
| Git state | Branch + commit at start and end |
| Git diff | Full diff (start → submit) |
| GitHub repo | Auto-created `interview-{code}` repo; code pushed on submit |
| Timestamps | Millisecond precision on every event |
| Session debrief | Claude's post-session reflection (written on /submit, stored as debrief.txt) |
| Session flags | Anomaly signals computed on submission (too fast, no iteration, uniform timing, etc.) |

The session log is append-only and hash-chained. Any tampering breaks the chain. The dashboard includes a **Verify Chain** button.

Raw file contents are never stored — only paths, hashes, and command summaries.

---

## Configuration reference

```bash
# Grading
interview configure-api-key    # Anthropic API key (direct access)
interview configure-llm        # Enterprise: custom endpoint, proxy, format, extra headers

# Delivery
interview configure-relay      # Relay URL + auto-register HM account
interview configure-email      # SMTP fallback (no relay)

# Runtime
interview dashboard            # Local HM dashboard at localhost:7832
interview dashboard <CODE>     # Filter dashboard to one interview's submissions
interview status               # Check active session
interview score <CODE>         # Candidate: fetch your score from relay
interview install --help       # Platform install options
```

All config stored in `~/.interview/config.json` (permissions: 600).

---

## Privacy

Candidate sessions stored on relay: `events.jsonl`, `manifest.json`, `report.html`, `report.json`, `debrief.txt`, `flags.json`. Raw file contents are never stored.

Grading sends the session timeline and git diff to the configured AI endpoint using your own API key — interviewsignal never sees it.

Self-hosted relay: nothing leaves your network. See [docs/relay-api.md](docs/relay-api.md).

No telemetry. No analytics. No tracking.

---

## Built with

Python stdlib only (no external dependencies for core or relay). Grading via [Anthropic Messages API](https://docs.anthropic.com/en/api) or any compatible endpoint. Dashboard is a self-contained local HTTP server. Reports are single-file HTML. Relay is a single-process stdlib HTTP server backed by flat files.

---

## Contributing

**Prompts** — the debrief and grading instructions are open and community-editable. See [`prompts/debrief.md`](prompts/debrief.md) for contribution guidelines. Good prompts improve what every candidate sees after every interview.

**Worked examples** — run a real session, save output to `worked/{slug}/`, write an honest `review.md`, open a PR.

**Platform support** — each new platform is a ~30 line adapter in `cli.py`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module responsibilities and [docs/relay-api.md](docs/relay-api.md) for the relay API contract.

---

<p align="center">
  <em>Broad-interview, not broadcast-reject. Pure signal.</em>
</p>

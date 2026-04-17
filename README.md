# interviewsignal

[![PyPI](https://img.shields.io/pypi/v/interviewsignal)](https://pypi.org/project/interviewsignal/)
[![Downloads](https://static.pepy.tech/badge/interviewsignal/month)](https://pepy.tech/project/interviewsignal)
[![GitHub](https://img.shields.io/badge/github-NikhilSKashyap%2Finterviewsignal-blue)](https://github.com/NikhilSKashyap/interviewsignal)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**An AI-native interview platform.** Type `/interview` in Claude Code, Codex, Cursor, or any AI coding assistant — it captures your entire thought process as you solve a problem and sends a structured, tamper-evident audit to the hiring manager.

No contrived puzzles. No whiteboard anxiety. Just signal.

---

## The problem

You're hiring a software engineer. You've spent 6 hours watching three candidates struggle with binary tree problems none of them will ever encounter on the job. One froze. One solved it but couldn't explain their thinking. One was brilliant but had a bad day.

You still don't know who can actually build software.

Meanwhile, every one of those candidates uses AI coding assistants every day. You tested them without their tools — like testing a surgeon without instruments.

**There's a better signal: how they think.**

---

## Install

```bash
pip install interviewsignal && interview install
```

Requires Python 3.10+ and one of: [Claude Code](https://claude.ai/code), [Codex](https://openai.com/codex), [Cursor](https://cursor.com), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Aider](https://aider.chat).

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
- Anonymize candidates? (yes / no — off by default; recommended for high-volume hiring)
- Score sharing level (what candidates can see after grading)

**Relay mode:** no email configuration needed — candidates go straight to your dashboard.
**Email mode only:** you'll also be asked for your email, CC list, and an audit recipient.

You get back a code like `INT-4829-XK`. Share it with your candidate — that's all they need.

### Candidate

```bash
pip install interviewsignal && interview install
/interview INT-4829-XK
```

If the relay has GitHub OAuth configured, a browser tab opens for GitHub login — one account, one submission. The problem appears once auth completes. A public GitHub repo (`interview-{code}`) is created automatically and a git remote named `interview` is wired up in your working directory. Work normally — ask the AI questions, write code, run tests. The session records everything automatically.

When done:

```
/submit
```

The session is sealed, pushed to the relay, and Claude writes a session debrief — an honest reflection on what you did well, what you missed, and how you used the AI. It's shown in the terminal immediately. Once the HM grades, you can also run:

```bash
interview score INT-4829-XK
```

to see your score (if the HM has enabled sharing).

### Hiring manager — review

```bash
interview dashboard   # → http://localhost:7832
```

Click into any candidate to see the full transcript (prompts + AI reasoning + tool calls), dimension scores, and diff. Add comments. Record your decision. If anonymization is enabled, candidates appear as "Candidate A", "Candidate B" — click Reveal when you're ready to unmask. Reveal is disabled until a grade is saved.

Use **Verify Chain** to confirm the session log is tamper-evident. Control what candidates see after grading with the **Score Sharing** panel — nothing, overall score, full breakdown, or breakdown with notes. Claude's session debrief is always shared automatically regardless of this setting.

---

## How it works

interviewsignal installs as a skill into your AI coding assistant. It captures the full conversation — prompts, AI reasoning before each action, every tool call (reads, writes, bash commands) — and builds an append-only, hash-chained session log. On `/submit`, the log is sealed and pushed to the relay. The HM grades from their dashboard using their own AI key.

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
  ↓ relay auto-configured locally         ↓ candidates arrive
Session starts                            ↓ Grade All / Grade Selected
  ↓ hooks capture every tool call         ↓ Reveal unlocks after grading
  ↓ append-only events.jsonl              ↓ comment thread
  ↓ hash chain (tamper-evident)           ↓ hire / next round / reject
/submit                                   ↓ full audit trail
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

**The integrity model:**

Every HM action — grading, revealing identity, adding a comment, recording a decision, revising a grade — is appended to a SHA-256 hash chain. In relay mode, the relay's server-side timestamp is the integrity anchor. In email mode, key events are silently emailed to a designated audit recipient with the mail server's timestamp as the anchor. Reveal is physically disabled until a grade is saved.

Grade revisions require an explicit reason. The audit records whether identity was revealed at revision time:

```
[2026-04-13T10:47:22Z] grade_recorded    INT-4829-XK  hash=d4abe5e6  score=7.7
[2026-04-13T10:52:09Z] identity_revealed INT-4829-XK  hash=2370be19
[2026-04-13T11:30:00Z] grade_revised     INT-4829-XK  hash=9f2c1a3b  7.7→8.2  revealed=true
```

Use `GET /audit/verify` to walk the full chain and confirm integrity.

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

Or with Docker:

```bash
docker run -e RELAY_API_KEY=secret -v /data:/data -p 8080:8080 \
  ghcr.io/nikhilskashyap/interviewsignal:latest
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

When configured, candidates see a browser auth step at session start. The relay enforces uniqueness server-side. On Reveal, the HM sees the candidate's GitHub username, avatar, and a link to their session repo.

Without GitHub OAuth, candidates are identified by email only.

See [docs/relay-api.md](docs/relay-api.md) for the full API contract and data layout.

### Option 2 — Email only (free, no server)

```bash
interview configure-relay   # choose 2
interview configure-email   # set up SMTP credentials
```

Reports are emailed directly to the HM on `/submit`. The HM saves the JSON attachment to `~/.interview/received/` and it appears in the dashboard.

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
  "grading_model":           "claude-3-5-haiku",
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

| Platform | Install | Hook mechanism |
|---|---|---|
| Claude Code (Linux/Mac/Windows) | `interview install` | PreToolUse + PostToolUse hooks |
| Codex | `interview install --platform codex` | PreToolUse hook + AGENTS.md |
| Cursor | `interview install --platform cursor` | `.cursor/rules/interview.mdc` |
| Gemini CLI | `interview install --platform gemini` | BeforeTool hook + GEMINI.md |
| Aider | `interview install --platform aider` | AGENTS.md |

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
interview status               # Check active session
interview score <CODE>         # Candidate: fetch your score from relay
interview install --help       # Platform install options
```

All config stored in `~/.interview/config.json` (permissions: 600).

---

## Privacy

Candidate sessions stored on relay: `events.jsonl`, `manifest.json`, `report.html`, `report.json`, `debrief.txt`. Raw file contents are never stored.

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
  <em>Thought process, not puzzles. Pure signal.</em>
</p>

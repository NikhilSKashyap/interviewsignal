# interviewsignal

[![PyPI](https://img.shields.io/pypi/v/interviewsignal)](https://pypi.org/project/interviewsignal/)
[![Downloads](https://static.pepy.tech/badge/interviewsignal/month)](https://pepy.tech/project/interviewsignal)
[![GitHub](https://img.shields.io/badge/github-NikhilSKashyap%2Finterviewsignal-blue)](https://github.com/NikhilSKashyap/interviewsignal)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**An AI-native interview platform.** Type `/interview` in Claude Code, Codex, Cursor, or any AI coding assistant — it captures your entire thought process as you solve a problem and sends a structured, tamper-evident audit to the hiring manager.

No contrived puzzles. No whiteboard anxiety. No bias. Just signal.

---

## The problem

You're hiring a software engineer. You've spent 6 hours watching three candidates struggle with binary tree problems none of them will ever encounter on the job. One froze. One solved it but couldn't explain their thinking. One was brilliant but had a bad day.

You still don't know who can actually build software.

Meanwhile, every one of those candidates uses AI coding assistants every day. You tested them without their tools — like testing a surgeon without instruments.

**There's a better signal: how they think.**

---

## What you get

**For hiring managers:**
- A timestamped audit of everything the candidate did — every prompt, every tool call, every file written
- AI grading against your own rubric (not a canned scoring system)
- Anonymous-first dashboard: you see scores before names, every time
- Grade-before-Reveal enforcement with a tamper-evident audit trail — provable merit-first hiring
- Comment threads, hire/reject decisions, all hash-chained and email-anchored

**For candidates:**
- Work the way you actually work — with AI assistance, in your own environment
- Get evaluated on your thinking, not your ability to memorise algorithms
- No file transfers, no email attachments — just a short code

**For teams:**
- Close the interview loop in half the time
- A written record of the hiring decision from problem to offer
- Works inside your existing toolchain — no new platform to log into

---

## Install

```bash
pip install interviewsignal && interview install
```

Requires Python 3.10+ and one of: [Claude Code](https://claude.ai/code), [Codex](https://openai.com/codex), [Cursor](https://cursor.com), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [Aider](https://aider.chat).

Then configure grading and (optionally) the relay:

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
- Your email + CC list (HR, co-interviewer, etc.)
- Audit recipient (HR or a neutral third party — receives a silent email on each key action)
- Time limit (optional)
- Anonymize candidates? (yes / no)

You get back a code like `INT-4829-XK`. Share it with your candidate — that's all they need.

### Candidate

```bash
pip install interviewsignal && interview install
```

```
/interview INT-4829-XK
```

The problem appears. Relay is auto-configured — no API keys or file transfers required. Work normally — ask the AI questions, write code, run tests. The session records everything automatically.

When done:

```
/submit
```

The session is sealed and sent to the relay. The hiring manager's dashboard updates automatically.

### Hiring manager — review

```bash
interview dashboard
# → http://localhost:7832
```

Candidates appear as "Candidate A", "Candidate B" — scores first, names second. Click into any candidate to see the full transcript (prompts + AI reasoning + tool calls), dimension scores, and diff. Add comments. Record your decision. Click Reveal when you're ready to unmask. Use **Verify Chain** to confirm the session log is tamper-evident.

---

## How it works

interviewsignal installs as a skill into your AI coding assistant. It captures the full conversation — the candidate's prompts, the AI's reasoning before each action, every tool call (reads, writes, bash commands) — and builds an append-only, hash-chained session log. On `/submit`, the log is sealed and pushed to the relay. The HM grades from their dashboard using their own AI key.

```
Candidate side                          HM side
─────────────────────────               ───────────────────────
interview configure-relay               interview configure-relay
  ↓ auto-registered via relay             ↓ gets unique hm_key

/interview hm                           ← share code INT-4829-XK
  ↓ creates interview
  ↓ pushes package to relay

/interview INT-4829-XK                  interview dashboard
  ↓ fetches problem from relay            ↓ localhost:7832
  ↓ relay auto-configured locally         ↓ candidates arrive
Session starts                            ↓ anonymous by default
  ↓ hooks capture every tool call         ↓ Grade All / Grade Selected
  ↓ append-only events.jsonl              ↓ score before name
  ↓ hash chain (tamper-evident)           ↓ Reveal unlocks after grading
/submit                                   ↓ comment thread
  ↓ session sealed                        ↓ hire / next round / reject
  ↓ pushed to relay                       ↓ full audit trail
```

**Three passes on submit:**
1. `session seal` — finalises hash chain, captures git diff (start → end)
2. Push to relay — sealed session (events + manifest + report) stored server-side
3. HM grades from dashboard — sends timeline + rubric + diff to their AI key, returns structured JSON scores

**The integrity model:**

Every HM action — grading, revealing identity, adding a comment, recording a decision — is logged with a SHA-256 hash chain. Key events are silently emailed to a designated audit recipient (typically HR). The mail server's timestamp is outside the HM's control. Reveal is physically disabled until a grade is saved, ensuring blind evaluation is provable.

```
[2026-04-13T10:47:22Z] grade_recorded       INT-4829-XK  hash=d4abe5e6
[2026-04-13T10:52:09Z] identity_revealed    INT-4829-XK  hash=2370be19
```

*"Identity revealed 4.8 minutes after grade was recorded."* That one line proves merit came first.

---

## Relay

The relay stores interview packages and candidate sessions so hiring managers and candidates only need to share a short code — no file transfers, no email attachments.

Run `interview configure-relay` to choose:

```
How do you want to deliver interview sessions?
──────────────────────────────────────────────
  1. Your own relay  Railway / Render / self-hosted — private, ~$5/mo
  2. Email only      SMTP — no server, reports arrive by email
```

### Option 1 — Your own relay (~$5/mo, fully private)

Deploy in one click:

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/NikhilSKashyap/interviewsignal)

After deploying:
1. Set environment variable `RELAY_API_KEY` (any random string) in Railway → Variables
2. Add a `/data` volume when prompted — this is where sessions are stored
3. Copy your Railway URL (e.g. `https://myrelay.up.railway.app`)
4. Run `interview configure-relay` → option 1 → paste URL

Your data stays in your own Railway account. Cost is ~$5/month (Railway Hobby plan).

Or run it anywhere with Docker:

```bash
docker run -e RELAY_API_KEY=secret -v /data:/data -p 8080:8080 \
  ghcr.io/nikhilskashyap/interviewsignal:latest
```

See [docs/self-hosting.md](docs/self-hosting.md) for data layout, backup, and key rotation.

### Option 2 — Email only (free, no server)

```bash
interview configure-relay   # choose 2
interview configure-email   # set up SMTP credentials
```

Candidates run `/submit` → report is emailed directly to the HM. The HM saves the JSON attachment to `~/.interview/received/` and it appears in the dashboard. No server needed, no ongoing cost. Trade-off: manual file handling and the dashboard can't re-grade from raw events.

---

## Enterprise configuration

Companies that don't issue personal API keys — or that route all AI traffic through an internal gateway — can configure a custom LLM endpoint:

```bash
interview configure-llm
```

This covers three patterns:

| Pattern | What to set |
|---|---|
| Anthropic direct | API key only (default) |
| Internal proxy (Floodgate, corporate gateway) | Base URL + optional key; proxy handles auth |
| OpenAI-compatible endpoint | Base URL + key + `format=openai` |

**What gets configured (`~/.interview/config.json`):**

```json
{
  "anthropic_base_url":      "https://ai-gateway.corp.internal/anthropic",
  "anthropic_api_key":       "",
  "api_format":              "anthropic",
  "grading_model":           "claude-3-5-haiku",
  "anthropic_extra_headers": {"X-Team-ID": "ml-hiring"}
}
```

The API key is optional — leave it blank if your proxy handles auth at the network or SSO level. Extra headers let you pass team/project routing headers required by some gateways.

Environment variable overrides (useful for CI or shared machines):

```bash
ANTHROPIC_API_KEY=...           # API key
ANTHROPIC_BASE_URL=...          # base URL override
INTERVIEW_GRADING_MODEL=...     # model name override
```

---

## True meritocracy

Most companies say they hire on merit. Almost none of them do — because the process doesn't allow it.

When you know who someone is before you evaluate them, bias isn't a failure of character. It's a failure of process. The name on the resume, the university on the screen share, the face on the Zoom — they all get into your head before the first line of code is written.

`interviewsignal` makes meritocracy structurally possible:

**Same tools, same environment.** Every candidate works with the same AI assistant they use on the job. The person who drilled Leetcode for six months has no advantage over the person who just builds things. The only variable is how well they think.

**You can't prevent a candidate from having a second screen. Neither can a Leetcode proctoring tool.** The difference is that with interviewsignal, gaming it well requires understanding the problem — and that's the signal.

**Score before name, always.** Grades are locked in before identity is revealed — not as a policy, but as a technical constraint. You cannot click Reveal until a score is saved. The order of events is cryptographically provable.

**A tamper-evident record.** Every action — grading, revealing identity, adding a comment, recording a decision — is hash-chained and email-anchored to a timestamp outside your control. The audit trail doesn't just log what happened. It proves it.

```
[2026-04-13T10:47:22Z] grade_recorded     INT-4829-XK  hash=d4abe5e6
[2026-04-13T10:52:09Z] identity_revealed  INT-4829-XK  hash=2370be19
```

*"Identity revealed 4.8 minutes after grade was recorded."*

That one line is the whole argument. You hired the person with the best score. You can prove it. Not because you were careful, but because the system made any other sequence impossible.

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
| Timestamps | Millisecond precision on every event |

The session log is append-only and hash-chained. Any tampering breaks the chain. The HM dashboard includes a **Verify Chain** button that re-derives every SHA-256 hash and flags any mismatch, along with the relay's server-side submission timestamp.

What is **not** captured: raw file contents (only paths and hashes, for privacy). The grader evaluates the conversation, timeline, and diff — not file contents.

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
interview install --help       # Platform install options
```

All config stored in `~/.interview/config.json` (permissions: 600).

---

## Privacy

**Candidate sessions** are stored on the relay (or locally, in email mode). The relay stores: `events.jsonl`, `manifest.json`, `report.html`, and `report.json`. Raw file contents are never stored — only paths, hashes, and command summaries.

**Grading** sends the session timeline and git diff to the configured AI endpoint (Anthropic API by default, or your enterprise proxy). No raw file contents. The grading call uses your own API key — interviewsignal never sees it.

**Self-hosted relay:** Run the relay inside your own infrastructure and nothing leaves your network. See [docs/self-hosting.md](docs/self-hosting.md).

No telemetry. No analytics. No tracking.

---

## Built with

Python stdlib only (no external dependencies for core or relay). Grading via [Anthropic Messages API](https://docs.anthropic.com/en/api) or any compatible endpoint. Dashboard is a self-contained local HTTP server. Reports are single-file HTML. Relay is a single-process stdlib HTTP server backed by flat files.

---

## Contributing

**Worked examples** are the most valuable contribution. Run a real interview session, save the output to `worked/{slug}/`, write an honest `review.md` evaluating what the grading got right and wrong, open a PR.

**Platform support** — each new platform is a ~30 line adapter in `cli.py`. If you use an AI coding tool not listed above, adding support is straightforward.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module responsibilities and [docs/relay-api.md](docs/relay-api.md) for the full relay API contract.

---

<p align="center">
  <em>Thought process, not puzzles. Pure signal.</em>
</p>

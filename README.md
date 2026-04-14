# interviewsignal

[![PyPI](https://img.shields.io/pypi/v/interviewsignal)](https://pypi.org/project/interviewsignal/)
[![Downloads](https://static.pepy.tech/badge/interviewsignal/month)](https://pepy.tech/project/interviewsignal)
[![CI](https://github.com/nikhilkashyap/interviewsignal/actions/workflows/ci.yml/badge.svg)](https://github.com/nikhilkashyap/interviewsignal/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**An AI-native interview platform.** Type `/interview` in Claude Code, Codex, Cursor, or any AI coding assistant — it captures your entire thought process as you solve a problem and sends a structured audit to the hiring manager.

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
- Anonymous-first dashboard: you see scores before names, eliminating identity bias
- Grade-before-Reveal enforcement with a tamper-evident audit trail — defensible in a DEI audit
- Comment threads, hire/reject decisions, all hash-chained and email-anchored

**For candidates:**
- Work the way you actually work — with AI assistance, in your own environment
- Get evaluated on your thinking, not your ability to memorise algorithms
- Receive a copy of your own submission

**For teams:**
- Close the interview loop in half the time
- A written record of the hiring decision from problem to offer
- Works inside your existing toolchain — no new platform to log into

---

## Install

```bash
pip install interviewsignal && interview install
```

Requires Python 3.10+ and one of: [Claude Code](https://claude.ai/code), [Codex](https://openai.com/codex), [Cursor](https://cursor.com), [Gemini CLI](https://github.com/google-gemini/gemini-cli), [GitHub Copilot CLI](https://docs.github.com/copilot/copilot-cli), or [Aider](https://aider.chat).

Store your Anthropic API key (used for grading):

```bash
interview configure-api-key
```

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
- Audit recipient (for DEI compliance)
- Time limit (optional)
- Anonymize candidates? (yes / no)

You get back a code like `INT-4829-XK`. Share it with your candidate.

### Candidate

```bash
pip install interviewsignal && interview install
```

```
/interview INT-4829-XK
```

The problem appears. Work normally — ask the AI questions, write code, run tests. The session records everything automatically.

When done:

```
/submit
```

The session is sealed, graded against the rubric, and a full report is emailed to the hiring manager. You get a copy too.

### Hiring manager — review

```bash
interview dashboard
# → http://localhost:7832
```

Candidates appear as "Candidate A", "Candidate B" — scores first, names second. Click into any candidate to see the full transcript, dimension scores, and diff. Add comments. Record your decision. Click Reveal when you're ready to unmask.

---

## How it works

interviewsignal installs as a skill into your AI coding assistant. It hooks into every tool call — reads, writes, bash commands — and builds an append-only, hash-chained session log. On `/submit`, the log is sealed, graded via the Anthropic API, and emailed as a self-contained HTML report.

```
Candidate side                          HM side
─────────────────────────               ───────────────────────
/interview INT-4829-XK                  /interview hm
  ↓ fetches problem                       ↓ creates interview code
Session starts                          Dashboard: localhost:7832
  ↓ hooks capture every tool call         ↓ candidates arrive
  ↓ append-only events.jsonl              ↓ anonymous by default
  ↓ hash chain (tamper-evident)           ↓ Grade All / Grade Selected
/submit                                   ↓ score before name
  ↓ session sealed                        ↓ Reveal unlocks after grading
  ↓ graded via Anthropic API              ↓ comment thread
  ↓ report.html generated                 ↓ hire / next round / reject
  ↓ emailed to HM + CC                    ↓ full audit trail
  ↓ copy to candidate
```

**Three passes on submit:**
1. `session seal` — finalises hash chain, captures git diff (start → end)
2. `grader grade` — sends session timeline + rubric + diff to Claude, returns structured JSON scores
3. `report generate` — produces a dark-mode self-contained HTML report

**The integrity model:**

Every HM action — grading, revealing identity, adding a comment, recording a decision — is logged to `~/.interview/audit.jsonl` with a SHA-256 hash chain. Key events are silently emailed to a designated audit recipient (typically HR). The mail server's timestamp is outside the HM's control. Reveal is physically disabled until a grade is saved, ensuring blind evaluation is provable.

```
[2026-04-13T10:47:22Z] grade_recorded       INT-4829-XK  hash=d4abe5e6
[2026-04-13T10:52:09Z] identity_revealed    INT-4829-XK  hash=2370be19
```

*"Identity revealed 4.8 minutes after grade was recorded."* That one line is your DEI proof.

---

## Platform support

| Platform | Install | Hook mechanism |
|---|---|---|
| Claude Code (Linux/Mac/Windows) | `interview install` | PreToolUse + PostToolUse hooks |
| Codex | `interview install --platform codex` | PreToolUse hook + AGENTS.md |
| Cursor | `interview install --platform cursor` | `.cursor/rules/interview.mdc` |
| Gemini CLI | `interview install --platform gemini` | BeforeTool hook + GEMINI.md |
| GitHub Copilot CLI | `interview install --platform copilot` | Skill file |
| Aider | `interview install --platform aider` | AGENTS.md |

---

## True meritocracy

Most companies say they hire on merit. Almost none of them do — because the process doesn't allow it.

When you know who someone is before you evaluate them, bias isn't a failure of character. It's a failure of process. The name on the resume, the university on the screen share, the face on the Zoom — they all get into your head before the first line of code is written.

`interviewsignal` makes meritocracy structurally possible:

**Same tools, same environment.** Every candidate works with the same AI assistant they use on the job. The person who drilled Leetcode for six months has no advantage over the person who just builds things. The only variable is how well they think.

**Score before name, always.** Grades are locked in before identity is revealed — not as a policy, but as a technical constraint. You cannot click Reveal until a score is saved. The order of events is cryptographically provable.

**A tamper-evident record.** Every action — grading, revealing identity, adding a comment, recording a decision — is hash-chained and email-anchored to a timestamp outside your control. The audit trail doesn't just log what happened. It proves it.

```
[2026-04-13T10:47:22Z] grade_recorded     INT-4829-XK  hash=d4abe5e6
[2026-04-13T10:52:09Z] identity_revealed  INT-4829-XK  hash=2370be19
```

*"Identity revealed 4.8 minutes after grade was recorded."*

That one line is the whole argument. You hired the person with the best score. You can prove it. Not because you were careful, but because the system made any other sequence impossible.

---

## What gets captured

| Event | Captured |
|---|---|
| File reads | Path |
| File writes | Path + content hash |
| Bash commands | Command + exit code |
| File edits | Path + change summary |
| Git state | Branch + commit at start and end |
| Git diff | Full diff (start → submit) |
| Timestamps | Millisecond precision on every event |

The session log is append-only and hash-chained. Any tampering breaks the chain.

What is **not** captured: file contents (only hashes and paths, for privacy). The grader evaluates the timeline and diff, not raw file contents.

---

## Worked example

See [`worked/rate-limiter/`](worked/rate-limiter/) for a complete example:
- Problem statement and rubric
- Full session transcript (47 minutes)
- AI grading output
- The HTML report an HM would receive

---

## Configuration

```bash
interview configure-api-key    # Anthropic API key (for grading)
interview configure-email      # SMTP credentials (for sending reports)
interview dashboard            # Local HM dashboard at localhost:7832
interview status               # Check active session
interview install --help       # Platform install options
```

All config stored in `~/.interview/config.json` (permissions: 600).

---

## Privacy

interviewsignal sends the session timeline and git diff to the Anthropic API for grading — the same API your AI coding assistant already uses. Raw file contents are never sent. All other data stays local.

No telemetry. No analytics. No server. The only network call is to the Anthropic API during grading, using your own API key.

---

## Built with

Python stdlib only (no dependencies for the core). Grading via [Anthropic Messages API](https://docs.anthropic.com/en/api). Dashboard is a self-contained local HTTP server. Reports are single-file HTML.

---

## Contributing

**Worked examples** are the most valuable contribution. Run a real interview session, save the output to `worked/{slug}/`, write an honest `review.md` evaluating what the grading got right and wrong, open a PR.

**Platform support** — each new platform is a ~30 line adapter in `cli.py`. If you use an AI coding tool not listed above, adding support is straightforward.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module responsibilities.

---

<p align="center">
  <em>Thought process, not puzzles. Pure signal.</em>
</p>

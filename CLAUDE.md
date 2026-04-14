# interviewsignal — Claude Code conventions

## What this project is
AI-native interview platform. Replaces Leetcode with a real-work signal.
Captures candidate thought process via AI coding assistant hooks. HM grades via dashboard.
See README.md for the full pitch. See ARCHITECTURE.md for module responsibilities.
See HANDOFF.md for full context if starting a new session after a long break.

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

## Framing (preserve in all user-facing copy)
- "True meritocracy" not "DEI compliance"
- "Score before name" not "anonymization for bias reduction"
- The audit trail proves the sequence, it doesn't just log it

## Commands
```bash
pip install -e .                    # install locally
interview install                   # install Claude Code skill + hooks
interview configure-relay           # set relay URL + API key
interview dashboard                 # open HM dashboard at localhost:7832
python -m interview.relay.server    # run relay server directly
docker compose up                   # run relay via Docker
```

## What's next
See HANDOFF.md → "What's next" section.
Priority: PyPI publish → host relay.interviewsignal.dev → self-hosting docs → multi-platform.

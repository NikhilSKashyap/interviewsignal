"""
interview.core.grader
---------------------
Grades a sealed session against the HM's rubric using the Anthropic Messages API.
Zero external dependencies — uses stdlib urllib only.

API key resolution order:
  1. ANTHROPIC_API_KEY environment variable
  2. ~/.interview/config.json  →  "anthropic_api_key"

Called by:
  - dashboard _run_grading()  (Grade / Grade All buttons)
  - /submit flow in SKILL.md  (python -m interview.core.grader grade --code ...)
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR = INTERVIEW_DIR / "sessions"
CONFIG_FILE = INTERVIEW_DIR / "config.json"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
GRADING_MODEL = "claude-3-5-haiku-20241022"   # fast + cheap, good enough for grading
MAX_TOKENS = 2048


# ─── API key ─────────────────────────────────────────────────────────────────

def _get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text()).get("anthropic_api_key", "")
        except Exception:
            pass
    return None


# ─── Transcript builder ───────────────────────────────────────────────────────

def build_transcript(code: str) -> str:
    """
    Convert events.jsonl into a readable timeline for the grading prompt.

    Format:
      [T+2min]  → Write      rate_limiter.py  (312 chars)
      [T+2min]  ← Write      ok
      [T+5min]  → Bash       python -m pytest
      [T+5min]  ← Bash       exit_code=0
    """
    events_file = SESSIONS_DIR / code / "events.jsonl"
    if not events_file.exists():
        return "(no session events found)"

    events = [
        json.loads(line)
        for line in events_file.read_text().splitlines()
        if line.strip()
    ]

    # Find session start time
    start_ts = None
    for e in events:
        if e["type"] == "session_start":
            start_ts = e["timestamp"]
            break
    if start_ts is None and events:
        start_ts = events[0]["timestamp"]

    lines = []
    for e in events:
        etype = e["type"]
        ts = e.get("timestamp", start_ts)
        elapsed = round((ts - start_ts) / 60, 1) if start_ts else 0
        tag = f"[T+{elapsed}min]"
        payload = e.get("payload", {})

        if etype == "session_start":
            git = payload.get("git_snapshot", {})
            commit = (git.get("commit") or "none")[:8]
            lines.append(f"{tag}  SESSION START  git={commit}")

        elif etype == "tool_call":
            tool = payload.get("tool_name", "?")
            inp = payload.get("tool_input", {})
            # Build a concise description of the tool input
            detail = _summarise_tool_input(tool, inp)
            lines.append(f"{tag}  → {tool:<12} {detail}")

        elif etype == "tool_result":
            tool = payload.get("tool_name", "?")
            summary = payload.get("response_summary", {})
            detail = _summarise_tool_result(tool, summary)
            lines.append(f"{tag}  ← {tool:<12} {detail}")

        elif etype == "session_end":
            elapsed_total = payload.get("elapsed_minutes", 0)
            lines.append(f"{tag}  SESSION END  total={elapsed_total}min")

    return "\n".join(lines)


def _summarise_tool_input(tool: str, inp: dict) -> str:
    if tool in ("Write", "Edit"):
        path = inp.get("file_path") or inp.get("path", "?")
        content = inp.get("content", "") or inp.get("new_string", "")
        return f"{path}  ({len(str(content))} chars)"
    if tool == "Read":
        return inp.get("file_path") or inp.get("path", "?")
    if tool in ("Bash", "bash"):
        cmd = str(inp.get("command", ""))[:80]
        return cmd
    if tool in ("Glob", "Grep"):
        return str(inp.get("pattern", inp))[:60]
    return str(inp)[:80]


def _summarise_tool_result(tool: str, summary: dict) -> str:
    if not summary:
        return "ok"
    # Common patterns
    if "exit_code" in summary:
        return f"exit={summary['exit_code']}"
    if "ok" in summary:
        return "ok" if summary["ok"] else "error"
    # Hash references from large outputs
    parts = []
    for k, v in list(summary.items())[:3]:
        parts.append(f"{k}={str(v)[:30]}")
    return "  ".join(parts) if parts else "ok"


# ─── Grading prompt ───────────────────────────────────────────────────────────

def _build_grading_prompt(manifest: dict, transcript: str) -> str:
    problem = manifest.get("problem", "(no problem statement)")
    rubric = manifest.get("rubric", "(no rubric)")
    git_diff = manifest.get("git_diff", "")
    elapsed = manifest.get("elapsed_minutes", 0)
    event_count = manifest.get("event_count", 0)

    # Truncate diff if very long
    if len(git_diff) > 3000:
        git_diff = git_diff[:3000] + f"\n... (truncated, {len(git_diff)} total chars)"

    return f"""You are grading a software engineering interview session.
The candidate used an AI coding assistant (Claude Code / Codex) to solve the problem.
Your job is to evaluate the QUALITY OF THEIR THINKING — how they decomposed the problem,
how they directed the AI, and how clean the final result is.

━━━ PROBLEM STATEMENT ━━━
{problem}

━━━ GRADING RUBRIC ━━━
{rubric}

━━━ SESSION STATS ━━━
Duration: {elapsed} minutes
Tool calls: {event_count}

━━━ SESSION TIMELINE (candidate's AI interactions) ━━━
{transcript}

━━━ FINAL CODE CHANGES (git diff) ━━━
{git_diff if git_diff.strip() else "(no git diff captured — evaluate from session timeline)"}

━━━ INSTRUCTIONS ━━━
1. Read the rubric carefully. Extract each distinct grading dimension from it.
2. Score each dimension 1–10. Be honest — a score of 5 means average, 8 means strong.
3. Write one specific, evidence-based justification per dimension (cite what you saw).
4. Compute overall_score as a weighted average matching the rubric's weighting.
   If no weights are specified, weight all dimensions equally.
5. Write a 2–3 sentence summary of the candidate's approach for the hiring manager.
6. List up to 3 standout_moments (specific impressive things you observed).
7. List up to 3 concerns (specific gaps or weaknesses — omit if none).

Respond with ONLY valid JSON, no markdown, no code fences. Schema:
{{
  "dimensions": [
    {{"name": "string", "score": 1-10, "justification": "string"}}
  ],
  "overall_score": 0.0,
  "summary": "string",
  "standout_moments": ["string"],
  "concerns": ["string"]
}}"""


# ─── API call ─────────────────────────────────────────────────────────────────

def _call_anthropic(prompt: str, api_key: str) -> str:
    """POST to Anthropic Messages API. Returns the text content of the response."""
    payload = {
        "model": GRADING_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=data,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
    return body["content"][0]["text"]


def _parse_grading_response(text: str) -> dict:
    """Parse the JSON grading response, with fallback for wrapped output."""
    text = text.strip()
    # Strip markdown fences if model wrapped it anyway
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()
    return json.loads(text)


# ─── Main grading function ────────────────────────────────────────────────────

class GradingError(Exception):
    pass


def grade_session(code: str) -> dict:
    """
    Grade a sealed session. Returns the grading dict.
    Raises GradingError with a human-readable message on failure.
    """
    # Load manifest
    manifest_file = SESSIONS_DIR / code / "manifest.json"
    if not manifest_file.exists():
        raise GradingError(
            f"No sealed session found for {code}. Run /submit first."
        )
    manifest = json.loads(manifest_file.read_text())

    # Check API key
    api_key = _get_api_key()
    if not api_key:
        raise GradingError(
            "No Anthropic API key found.\n"
            "Run: interview configure-api-key\n"
            "Or set: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    # Build prompt
    transcript = build_transcript(code)
    prompt = _build_grading_prompt(manifest, transcript)

    # Call API
    try:
        raw = _call_anthropic(prompt, api_key)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise GradingError(f"Anthropic API error {e.code}: {body}")
    except Exception as e:
        raise GradingError(f"API call failed: {e}")

    # Parse response
    try:
        grading = _parse_grading_response(raw)
    except json.JSONDecodeError as e:
        raise GradingError(f"Could not parse grading response as JSON: {e}\nRaw: {raw[:200]}")

    # Validate shape
    if "overall_score" not in grading or "dimensions" not in grading:
        raise GradingError(f"Unexpected grading response shape: {list(grading.keys())}")

    # Save via decisions.save_grade (which also audit-logs)
    from interview.core.decisions import save_grade
    return save_grade(code, grading)


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Grade an interview session")
    parser.add_argument("command", choices=["grade", "transcript"])
    parser.add_argument("--code", required=True)
    args = parser.parse_args()

    if args.command == "grade":
        print(f"\nGrading session {args.code}...")
        try:
            result = grade_session(args.code)
            score = result.get("overall_score", "—")
            summary = result.get("summary", "")
            dims = result.get("dimensions", [])
            print(f"\n  Overall: {score}/10")
            print(f"  Summary: {summary}\n")
            for d in dims:
                print(f"  {d['name']:<30} {d['score']}/10  — {d.get('justification','')[:60]}")
            print(f"\n✓ Grading complete. Reveal is now unlocked in the dashboard.\n")
        except GradingError as e:
            print(f"\n✗ Grading failed:\n  {e}\n")

    elif args.command == "transcript":
        print(build_transcript(args.code))


if __name__ == "__main__":
    main()

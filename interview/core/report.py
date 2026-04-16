"""
interview.core.report
---------------------
Generates the self-contained HTML report and machine-readable JSON
from a sealed session. The HTML is the email attachment HMs open.
"""

import argparse
import json
import time
from pathlib import Path

INTERVIEW_DIR = Path.home() / ".interview"
SESSIONS_DIR = INTERVIEW_DIR / "sessions"


def _load_manifest(code: str) -> dict:
    f = SESSIONS_DIR / code / "manifest.json"
    if not f.exists():
        raise FileNotFoundError(f"No sealed session found for {code}. Run /submit first.")
    return json.loads(f.read_text())


def _load_events(code: str) -> list[dict]:
    f = SESSIONS_DIR / code / "events.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def _load_grading(code: str) -> dict | None:
    f = SESSIONS_DIR / code / "grading.json"
    if f.exists():
        return json.loads(f.read_text())
    return None


def _format_timestamp(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _event_to_html_row(event: dict) -> str:
    ts = _format_timestamp(event["timestamp"])
    etype = event["type"]
    payload = event.get("payload", {})

    if etype == "session_start":
        return f"""
        <div class="event event-start">
          <span class="event-time">{ts}</span>
          <span class="event-type">Session Started</span>
          <div class="event-detail">Git: {((payload.get('git_snapshot') or {}).get('commit') or 'N/A')[:8]}</div>
        </div>"""

    elif etype == "tool_call":
        tool = payload.get("tool_name", "")
        inputs = json.dumps(payload.get("tool_input", {}), indent=2)[:400]
        return f"""
        <div class="event event-tool">
          <span class="event-time">{ts}</span>
          <span class="event-type">→ {tool}</span>
          <pre class="event-detail">{inputs}</pre>
        </div>"""

    elif etype == "tool_result":
        tool = payload.get("tool_name", "")
        summary = json.dumps(payload.get("response_summary", {}))[:200]
        return f"""
        <div class="event event-result">
          <span class="event-time">{ts}</span>
          <span class="event-type">← {tool}</span>
          <div class="event-detail small">{summary}</div>
        </div>"""

    elif etype == "user_prompt":
        text = payload.get("text", "")
        return f"""
        <div class="event event-user-prompt">
          <span class="event-time">{ts}</span>
          <span class="event-type">candidate</span>
          <div class="event-detail">{text}</div>
        </div>"""

    elif etype == "thinking":
        plan = payload.get("plan", payload.get("text", payload.get("reasoning", "")))
        return f"""
        <div class="event event-thinking">
          <span class="event-time">{ts}</span>
          <span class="event-type">thinking</span>
          <div class="event-detail">{plan}</div>
        </div>"""

    elif etype == "assistant_message":
        text = payload.get("text", "")
        return f"""
        <div class="event event-assistant">
          <span class="event-time">{ts}</span>
          <span class="event-type">assistant</span>
          <div class="event-detail">{text}</div>
        </div>"""

    elif etype == "session_end":
        elapsed = payload.get("elapsed_minutes", 0)
        return f"""
        <div class="event event-end">
          <span class="event-time">{ts}</span>
          <span class="event-type">Session Ended</span>
          <div class="event-detail">Duration: {elapsed} minutes</div>
        </div>"""

    return ""


def _grading_html(grading: dict | None) -> str:
    if not grading:
        return "<p class='no-grade'>Not yet graded.</p>"

    dims_html = ""
    for d in grading.get("dimensions", []):
        score = d.get("score", 0)
        bar_width = score * 10
        color = "#22c55e" if score >= 7 else "#f59e0b" if score >= 5 else "#ef4444"
        dims_html += f"""
        <div class="dim-row">
          <div class="dim-name">{d['name']}</div>
          <div class="dim-bar-wrap">
            <div class="dim-bar" style="width:{bar_width}%;background:{color}"></div>
          </div>
          <div class="dim-score">{score}/10</div>
          <div class="dim-just">{d.get('justification','')}</div>
        </div>"""

    overall = grading.get("overall_score", 0)
    summary = grading.get("summary", "")
    standouts = "".join(f"<li>{s}</li>" for s in grading.get("standout_moments", []))
    concerns = "".join(f"<li>{c}</li>" for c in grading.get("concerns", []))

    return f"""
    <div class="overall-score">Overall: <strong>{overall}/10</strong></div>
    <p class="summary">{summary}</p>
    <div class="dims">{dims_html}</div>
    {"<div class='standouts'><h4>Standout Moments</h4><ul>" + standouts + "</ul></div>" if standouts else ""}
    {"<div class='concerns'><h4>Watch Points</h4><ul>" + concerns + "</ul></div>" if concerns else ""}
    """


def generate_html_report(code: str) -> str:
    manifest = _load_manifest(code)
    events = _load_events(code)
    grading = _load_grading(code)

    events_html = "\n".join(_event_to_html_row(e) for e in events)
    grading_html = _grading_html(grading)

    overall = grading.get("overall_score", "—") if grading else "—"
    started = _format_timestamp(manifest["started_at"])
    ended = _format_timestamp(manifest.get("ended_at", manifest["started_at"]))
    elapsed = manifest.get("elapsed_minutes", 0)

    # Syntax-highlight the git diff
    diff_lines = manifest.get("git_diff", "")
    diff_html = ""
    for line in diff_lines.splitlines()[:200]:  # cap at 200 lines for readability
        if line.startswith("+") and not line.startswith("+++"):
            diff_html += f'<div class="diff-add">{line}</div>'
        elif line.startswith("-") and not line.startswith("---"):
            diff_html += f'<div class="diff-del">{line}</div>'
        elif line.startswith("@@"):
            diff_html += f'<div class="diff-hunk">{line}</div>'
        else:
            diff_html += f'<div class="diff-ctx">{line}</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Interview Report — {code}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f0f0f; color: #e0e0e0; line-height: 1.6; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 32px 24px; }}
  .header {{ border-bottom: 1px solid #333; padding-bottom: 24px; margin-bottom: 32px; }}
  .header h1 {{ font-size: 28px; font-weight: 700; color: #fff; }}
  .header .meta {{ color: #888; font-size: 14px; margin-top: 8px; }}
  .badge {{ display: inline-block; background: #1a1a2e; border: 1px solid #333;
            padding: 2px 10px; border-radius: 12px; font-size: 12px; margin-right: 8px; }}
  .score-badge {{ background: #0d2137; border-color: #1d4ed8; color: #60a5fa; font-size: 18px;
                  padding: 4px 16px; font-weight: 700; }}
  section {{ margin-bottom: 40px; }}
  h2 {{ font-size: 16px; font-weight: 600; color: #a0a0a0; text-transform: uppercase;
         letter-spacing: 0.08em; margin-bottom: 16px; padding-bottom: 8px;
         border-bottom: 1px solid #222; }}
  .problem-box {{ background: #161616; border: 1px solid #333; border-radius: 8px;
                  padding: 20px; white-space: pre-wrap; font-size: 14px; }}
  .grading-box {{ background: #161616; border: 1px solid #333; border-radius: 8px; padding: 20px; }}
  .overall-score {{ font-size: 22px; margin-bottom: 12px; }}
  .overall-score strong {{ color: #60a5fa; }}
  .summary {{ color: #ccc; font-size: 14px; margin-bottom: 20px; }}
  .dim-row {{ display: grid; grid-template-columns: 180px 1fr 60px; gap: 12px;
              align-items: center; margin-bottom: 12px; }}
  .dim-name {{ font-size: 13px; font-weight: 500; }}
  .dim-bar-wrap {{ background: #222; border-radius: 4px; height: 8px; }}
  .dim-bar {{ height: 8px; border-radius: 4px; transition: width 0.3s; }}
  .dim-score {{ font-size: 13px; font-weight: 600; text-align: right; }}
  .dim-just {{ grid-column: 1/-1; font-size: 12px; color: #888; padding-left: 192px; }}
  .standouts, .concerns {{ margin-top: 16px; }}
  .standouts h4 {{ color: #22c55e; font-size: 13px; margin-bottom: 8px; }}
  .concerns h4 {{ color: #f59e0b; font-size: 13px; margin-bottom: 8px; }}
  ul {{ padding-left: 20px; font-size: 13px; color: #bbb; }}
  li {{ margin-bottom: 4px; }}
  .timeline {{ display: flex; flex-direction: column; gap: 4px; }}
  .event {{ display: grid; grid-template-columns: 140px 160px 1fr;
             gap: 12px; padding: 8px 12px; border-radius: 6px;
             font-size: 12px; align-items: start; }}
  .event-start {{ background: #0d2137; }}
  .event-end {{ background: #0d2137; }}
  .event-tool {{ background: #161616; }}
  .event-result {{ background: #111; }}
  .event-user-prompt {{ background: #1a1a0d; border-left: 3px solid #a3a300; }}
  .event-thinking {{ background: #0d1a0d; border-left: 3px solid #22c55e; }}
  .event-assistant {{ background: #0d0d1a; border-left: 3px solid #818cf8; }}
  .event-time {{ color: #666; font-family: monospace; }}
  .event-type {{ font-weight: 600; color: #a0a0a0; }}
  .event-tool .event-type {{ color: #60a5fa; }}
  .event-result .event-type {{ color: #888; }}
  .event-user-prompt .event-type {{ color: #d4d400; }}
  .event-thinking .event-type {{ color: #4ade80; }}
  .event-assistant .event-type {{ color: #a5b4fc; }}
  .event-detail {{ color: #bbb; white-space: pre-wrap; font-size: 11px; }}
  .event-detail.small {{ font-size: 10px; color: #666; }}
  pre.event-detail {{ font-family: monospace; }}
  .diff-wrap {{ font-family: monospace; font-size: 12px; background: #0a0a0a;
                border: 1px solid #222; border-radius: 8px; padding: 16px; overflow-x: auto; }}
  .diff-add {{ color: #4ade80; }}
  .diff-del {{ color: #f87171; }}
  .diff-hunk {{ color: #60a5fa; margin: 8px 0 4px; }}
  .diff-ctx {{ color: #555; }}
  .integrity {{ background: #0a1a0a; border: 1px solid #166534; border-radius: 8px; padding: 16px; }}
  .integrity .label {{ color: #4ade80; font-size: 12px; font-weight: 600; margin-bottom: 8px; }}
  .integrity .hash {{ font-family: monospace; font-size: 11px; color: #555; }}
  .no-grade {{ color: #666; font-size: 14px; }}
  footer {{ margin-top: 48px; padding-top: 24px; border-top: 1px solid #222;
             font-size: 11px; color: #444; text-align: center; }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>Interview Report</h1>
    <div class="meta">
      <span class="badge">{code}</span>
      <span class="badge">{started} → {ended}</span>
      <span class="badge">{elapsed} min</span>
      <span class="badge score-badge">⭐ {overall} / 10</span>
    </div>
  </div>

  <section>
    <h2>Problem Statement</h2>
    <div class="problem-box">{manifest.get('problem', '')}</div>
  </section>

  <section>
    <h2>Grading</h2>
    <div class="grading-box">{grading_html}</div>
  </section>

  <section>
    <h2>Session Timeline ({len(events)} events)</h2>
    <div class="timeline">{events_html}</div>
  </section>

  <section>
    <h2>Code Changes</h2>
    <div class="diff-wrap">{diff_html if diff_html else '<span style="color:#555">No git diff captured.</span>'}</div>
  </section>

  <section>
    <h2>Integrity</h2>
    <div class="integrity">
      <div class="label">✓ Hash-chained session log — tamper-evident</div>
      <div class="hash">Final hash: {manifest.get('final_hash', 'N/A')}</div>
      <div class="hash">Events: {manifest.get('event_count', 0)} | Sealed: {str(manifest.get('sealed', False))}</div>
    </div>
  </section>

  <footer>Generated by interviewsignal · {_format_timestamp(time.time())}</footer>

</div>
</body>
</html>"""

    return html


def generate_report(code: str):
    html = generate_html_report(code)
    manifest = _load_manifest(code)
    grading = _load_grading(code)

    # Write HTML report
    report_dir = SESSIONS_DIR / code
    html_file = report_dir / "report.html"
    html_file.write_text(html)

    # Write JSON report (for dashboard)
    json_report = {
        "code": code,
        "started_at": manifest["started_at"],
        "ended_at": manifest.get("ended_at"),
        "elapsed_minutes": manifest.get("elapsed_minutes"),
        "overall_score": grading.get("overall_score") if grading else None,
        "dimensions": grading.get("dimensions", []) if grading else [],
        "summary": grading.get("summary", "") if grading else "",
        "standout_moments": grading.get("standout_moments", []) if grading else [],
        "concerns": grading.get("concerns", []) if grading else [],
        "event_count": manifest.get("event_count", 0),
        "final_hash": manifest.get("final_hash"),
        "html_report": str(html_file),
    }
    json_file = report_dir / "report.json"
    json_file.write_text(json.dumps(json_report, indent=2))

    print(f"✓ Report generated:")
    print(f"  HTML: {html_file}")
    print(f"  JSON: {json_file}")

    return str(html_file), str(json_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate"])
    parser.add_argument("--code", required=True)
    args = parser.parse_args()

    if args.command == "generate":
        generate_report(args.code)


if __name__ == "__main__":
    main()

"""
interview.dashboard.serve
--------------------------
Local web dashboard for hiring managers.
Runs at http://localhost:7832

Transport-aware: if relay_url is set in ~/.interview/config.json, the dashboard
reads from and writes to the relay. Otherwise falls back to local file reads
(email attachments saved to ~/.interview/received/).

Multi-tenant relay (Model B): sessions are scoped by hm_key. Each candidate
is identified by cid (sha256 of email[:12]). All action endpoints accept cid
and thread it through to the relay.
"""

import http.server
import json
import os
import time
import urllib.error
import urllib.request
import webbrowser
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote

from interview.core.transport import get_relay_url, get_transport

INTERVIEW_DIR = Path.home() / ".interview"
RECEIVED_DIR  = INTERVIEW_DIR / "received"
SESSIONS_DIR  = INTERVIEW_DIR / "sessions"
PORT = 7832


def ensure_dirs():
    RECEIVED_DIR.mkdir(parents=True, exist_ok=True)


def _load_all_reports() -> list[dict]:
    """
    Load session summaries via transport.
    Relay mode  → fetches from relay.
    Email mode  → reads local sessions/ and received/ directories.
    """
    transport = get_transport()

    if get_relay_url():
        # Relay: fetch live list; normalise field names to match local shape
        sessions = transport.list_sessions()
        reports = []
        for s in sessions:
            r = dict(s)
            r.setdefault("_source", "relay")
            r.setdefault("_anonymize", s.get("anonymize", False))
            reports.append(r)
        return reports

    # Email / local mode — original behaviour
    reports = []

    if SESSIONS_DIR.exists():
        for session_dir in SESSIONS_DIR.iterdir():
            if session_dir.is_dir():
                report_file = session_dir / "report.json"
                if report_file.exists():
                    try:
                        r = json.loads(report_file.read_text())
                        r["_source"] = "local"
                        manifest_file = session_dir / "manifest.json"
                        if manifest_file.exists():
                            manifest = json.loads(manifest_file.read_text())
                            r["_anonymize"] = manifest.get("anonymize", True)
                        else:
                            r["_anonymize"] = True
                        reports.append(r)
                    except Exception:
                        pass

    if RECEIVED_DIR.exists():
        for f in RECEIVED_DIR.glob("*.json"):
            try:
                r = json.loads(f.read_text())
                r["_source"] = "received"
                r.setdefault("_anonymize", True)
                reports.append(r)
            except Exception:
                pass

    reports.sort(key=lambda r: r.get("ended_at") or r.get("started_at") or 0, reverse=True)
    return reports


def _ensure_local_cache(code: str, cid: str = ""):
    """
    In relay mode: download events.jsonl and manifest.json to the local
    sessions directory so grader.py (which reads local files) can work normally.
    No-op in email mode or if files already exist.
    """
    if not get_relay_url():
        return
    session_dir = SESSIONS_DIR / code
    session_dir.mkdir(parents=True, exist_ok=True)

    transport = get_transport()
    session = transport.get_session(code, cid or None)
    if not session:
        return

    # Write manifest if missing
    manifest_file = session_dir / "manifest.json"
    if not manifest_file.exists():
        manifest = session.get("manifest")
        if manifest:
            manifest_file.write_text(json.dumps(manifest, indent=2))

    # Fetch raw events.jsonl from relay
    events_file = session_dir / "events.jsonl"
    if not events_file.exists():
        try:
            from interview.core.transport import get_hm_key, get_relay_api_key
            relay_url = get_relay_url()
            token = get_hm_key() or get_relay_api_key()
            path = f"/sessions/{code}/{cid}/events" if cid else f"/sessions/{code}/events"
            req = urllib.request.Request(
                f"{relay_url}{path}",
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                events_file.write_bytes(resp.read())
        except Exception:
            pass


def _apply_labels(reports: list[dict]) -> list[dict]:
    """
    Assign display labels based on each report's anonymize setting.
    - anonymize=True  → 'Candidate A', 'Candidate B'... with a Reveal button
    - anonymize=False → interview code shown directly, no Reveal button needed
    """
    result = []
    anon_counter = 0
    for r in reports:
        labeled = dict(r)
        if r.get("_anonymize", True):
            labeled["_display_label"] = f"Candidate {chr(65 + anon_counter)}"
            labeled["_show_reveal"] = True
            anon_counter += 1
        else:
            github_username = r.get("github_username", "")
            if github_username:
                labeled["_display_label"] = f"@{github_username}"
            else:
                labeled["_display_label"] = r["code"]
            labeled["_show_reveal"] = False
        result.append(labeled)
    return result


def _format_time(ts: float | str | None) -> str:
    if not ts:
        return "—"
    if isinstance(ts, str):
        return ts[:16].replace("T", " ")
    return time.strftime("%b %d, %H:%M", time.localtime(ts))


def _score_color(score) -> str:
    if score is None:
        return "#666"
    if score >= 8:
        return "#22c55e"
    if score >= 6:
        return "#f59e0b"
    return "#ef4444"


def _build_candidate_row(r: dict) -> str:
    from interview.core.decisions import is_graded, get_decision

    label = r["_display_label"]
    show_reveal = r.get("_show_reveal", False)
    score = r.get("overall_score")
    score_str = f"{score}/10" if score is not None else "Pending"
    score_col = _score_color(score)
    elapsed = r.get("elapsed_minutes", "—")
    submitted = _format_time(r.get("submitted_at") or r.get("ended_at"))
    event_count = r.get("event_count", "—")
    code = r["code"]
    cid = r.get("cid", "")

    # Relay mode: graded/revealed state comes from relay summary data
    if r.get("_source") == "relay":
        graded = r.get("graded", False)
        decision_obj = None  # Decision shown on detail page only
    else:
        graded = is_graded(code)
        decision_obj = get_decision(code)

    # Reveal button: only shown for anonymized interviews AND only enabled after grading
    if show_reveal:
        if graded:
            reveal_btn = (
                f'<button class="btn btn-sm btn-reveal"'
                f' data-code="{code}" data-cid="{cid}">Reveal</button>'
            )
        else:
            reveal_btn = (
                f'<span class="badge-pending">Pending Grade</span>'
                f'<button class="btn btn-sm btn-reveal"'
                f' data-code="{code}" data-cid="{cid}"'
                f' disabled title="Grade this candidate first to unlock Reveal">Reveal 🔒</button>'
            )
    else:
        reveal_btn = ""

    # Decision badge (local mode only)
    decision_badge = ""
    if decision_obj:
        d = decision_obj["decision"]
        d_color = {"hire": "#22c55e", "next_round": "#60a5fa", "reject": "#ef4444"}.get(d, "#888")
        d_label = {"hire": "✓ Hired", "next_round": "→ Next Round", "reject": "✗ Rejected"}.get(d, d)
        decision_badge = f' <span style="color:{d_color};font-size:11px;font-weight:600">{d_label}</span>'

    view_url = (
        f"/candidate?code={quote(code, safe='')}&cid={quote(cid, safe='')}"
        if cid else
        f"/candidate?code={quote(code, safe='')}"
    )

    return f"""
    <tr data-code="{code}" data-cid="{cid}">
      <td class="td-label">
        <input type="checkbox" class="candidate-checkbox" data-code="{code}" data-cid="{cid}">
        <span class="display-label">{label}</span>{decision_badge}
      </td>
      <td><span class="score-badge" style="color:{score_col}">{score_str}</span></td>
      <td>{elapsed} min</td>
      <td>{event_count}</td>
      <td>{submitted}</td>
      <td>
        <a class="btn btn-sm" href="{view_url}" target="_blank">View</a>
        <button class="btn btn-sm btn-grade" data-code="{code}" data-cid="{cid}">Grade</button>
        {reveal_btn}
      </td>
    </tr>"""


SHARED_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f0f0f; color: #e0e0e0; }
  .topbar { background: #111; border-bottom: 1px solid #222;
            padding: 16px 32px; display: flex; align-items: center; gap: 16px; }
  .topbar h1 { font-size: 18px; font-weight: 700; color: #fff; }
  .topbar .tagline { font-size: 12px; color: #666; }
  .topbar a { margin-left: auto; font-size: 13px; color: #60a5fa; text-decoration: none; }
  .main { padding: 32px; max-width: 1100px; margin: 0 auto; }
  .btn { background: #1a1a1a; border: 1px solid #333; color: #ccc; padding: 6px 14px;
         border-radius: 6px; cursor: pointer; font-size: 13px; text-decoration: none;
         transition: all 0.15s; display: inline-block; }
  .btn:hover { background: #252525; border-color: #555; color: #fff; }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .btn-primary { background: #1d4ed8; border-color: #1d4ed8; color: #fff; }
  .btn-primary:hover { background: #2563eb; }
  .btn-sm { padding: 4px 10px; font-size: 12px; }
  .btn-grade { border-color: #854d0e; color: #fbbf24; }
  .btn-hire { border-color: #166534; color: #4ade80; }
  .btn-next { border-color: #1e40af; color: #60a5fa; }
  .btn-reject { border-color: #7f1d1d; color: #f87171; }
  .badge-pending { background: #2d1a00; border: 1px solid #854d0e; color: #fbbf24;
                   font-size: 10px; padding: 2px 7px; border-radius: 10px;
                   margin-right: 6px; vertical-align: middle; }
  .score-badge { font-weight: 700; font-size: 15px; }
  .section-title { font-size: 12px; font-weight: 600; color: #666; text-transform: uppercase;
                   letter-spacing: 0.08em; margin-bottom: 12px; padding-bottom: 8px;
                   border-bottom: 1px solid #222; }
"""


def _build_dashboard_html(reports: list[dict]) -> str:
    labeled_reports = _apply_labels(reports)
    rows = "\n".join(_build_candidate_row(r) for r in labeled_reports)
    count = len(reports)
    graded = sum(1 for r in reports if r.get("overall_score") is not None)
    avg_score = round(
        sum(r["overall_score"] for r in reports if r.get("overall_score") is not None) / graded, 1
    ) if graded else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>interviewsignal Dashboard</title>
<style>
  {SHARED_CSS}
  .stats {{ display: flex; gap: 24px; margin-bottom: 32px; }}
  .stat {{ background: #161616; border: 1px solid #222; border-radius: 8px; padding: 16px 24px; }}
  .stat-val {{ font-size: 28px; font-weight: 700; color: #fff; }}
  .stat-label {{ font-size: 12px; color: #666; margin-top: 4px; }}
  .toolbar {{ display: flex; gap: 12px; margin-bottom: 16px; align-items: center; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{ text-align: left; font-size: 11px; font-weight: 600; color: #666;
              text-transform: uppercase; letter-spacing: 0.06em;
              padding: 8px 16px; border-bottom: 1px solid #222; }}
  tbody tr {{ border-bottom: 1px solid #1a1a1a; }}
  tbody tr:hover {{ background: #161616; }}
  td {{ padding: 12px 16px; font-size: 13px; vertical-align: middle; }}
  .td-label {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .display-label {{ font-weight: 600; color: #e0e0e0; }}
  .empty {{ text-align: center; padding: 64px; color: #444; }}
  .received-hint {{ background: #111; border: 1px solid #333; border-radius: 8px;
                    padding: 16px; margin-bottom: 24px; font-size: 13px; color: #888; }}
  .received-hint strong {{ color: #ccc; }}
  code {{ font-family: monospace; font-size: 12px; color: #555; }}
  .audit-link {{ font-size: 11px; color: #444; margin-left: auto; }}
  .audit-link a {{ color: #444; text-decoration: none; }}
  .audit-link a:hover {{ color: #888; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>interviewsignal</h1>
  <span class="tagline">Thought process, not puzzles.</span>
  <a href="/audit">Audit Log ↗</a>
</div>
<div class="main">

  <div class="stats">
    <div class="stat"><div class="stat-val">{count}</div><div class="stat-label">Candidates</div></div>
    <div class="stat"><div class="stat-val">{graded}</div><div class="stat-label">Graded</div></div>
    <div class="stat"><div class="stat-val">{avg_score}</div><div class="stat-label">Avg Score</div></div>
  </div>

  {'<div class="received-hint"><strong>Relay connected.</strong> Submissions appear automatically when candidates run /submit.</div>'
   if get_relay_url() else
   '<div class="received-hint"><strong>To add submissions:</strong> save <code>interview_report_*.json</code> email attachments to <code>~/.interview/received/</code> — they appear here automatically.</div>'}

  <div class="toolbar">
    <button class="btn btn-primary" id="btn-grade-selected">Grade Selected</button>
    <button class="btn" id="btn-grade-all">Grade All</button>
    <button class="btn" onclick="location.reload()">↻ Refresh</button>
  </div>

  {'<table><thead><tr><th><input type="checkbox" id="select-all"> Candidate</th><th>Score</th><th>Duration</th><th>Events</th><th>Submitted</th><th>Actions</th></tr></thead><tbody>' + rows + '</tbody></table>'
   if reports else
   '<div class="empty"><h3>No submissions yet.</h3><p>Candidates appear here after /submit.</p></div>'}

</div>
<script>
  document.getElementById('select-all')?.addEventListener('change', function() {{
    document.querySelectorAll('.candidate-checkbox').forEach(cb => cb.checked = this.checked);
  }});
  document.getElementById('btn-grade-selected')?.addEventListener('click', function() {{
    const entries = [...document.querySelectorAll('.candidate-checkbox:checked')]
      .map(cb => ({{code: cb.dataset.code, cid: cb.dataset.cid || ''}}));
    if (!entries.length) {{ alert('Select at least one candidate.'); return; }}
    gradeMultiple(entries);
  }});
  document.getElementById('btn-grade-all')?.addEventListener('click', function() {{
    const entries = [...document.querySelectorAll('.candidate-checkbox')]
      .map(cb => ({{code: cb.dataset.code, cid: cb.dataset.cid || ''}}));
    gradeMultiple(entries);
  }});
  document.querySelectorAll('.btn-grade').forEach(btn =>
    btn.addEventListener('click', () =>
      gradeMultiple([{{code: btn.dataset.code, cid: btn.dataset.cid || ''}}]))
  );
  document.querySelectorAll('.btn-reveal').forEach(btn => {{
    btn.addEventListener('click', function() {{
      if (this.disabled) return;
      const row = this.closest('tr');
      const label = row.querySelector('.display-label');
      fetch('/reveal', {{method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{code: btn.dataset.code, cid: btn.dataset.cid || ''}})}})
        .then(r => r.json())
        .then(d => {{
          label.textContent = d.candidate_email || d.code;
          this.style.display = 'none';
          if (d.delta) {{
            const note = document.createElement('span');
            note.style.cssText = 'font-size:10px;color:#666;margin-left:8px';
            note.textContent = '(' + d.delta + ')';
            label.after(note);
          }}
        }});
    }});
  }});
  function gradeMultiple(entries) {{
    fetch('/grade', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{entries}})}})
      .then(r => r.json()).then(d => {{ alert(d.message); location.reload(); }})
      .catch(e => alert('Grade failed: ' + e));
  }}
</script>
</body>
</html>"""


def _build_candidate_detail_html(code: str, cid: str = "") -> str:
    """Full candidate detail page: report + comments + decision buttons."""
    from interview.core.decisions import get_comments, get_decision, is_graded
    from interview.core.audit import read_events as read_audit_events, get_reveal_delta

    # In relay mode with cid, fetch all state from the relay session object
    relay_session = None
    if get_relay_url() and cid:
        transport = get_transport()
        relay_session = transport.get_session(code, cid)

    if relay_session:
        raw_comments    = relay_session.get("comments", [])
        decision_obj    = relay_session.get("decision")
        graded          = relay_session.get("grading") is not None
        audit_events    = relay_session.get("audit_entries", [])
        revealed        = relay_session.get("revealed", False)
        current_grading = relay_session.get("grading") or {}
        grading_history = relay_session.get("grading_history", [])
    else:
        raw_comments    = get_comments(code)
        decision_obj    = get_decision(code)
        graded          = is_graded(code)
        audit_events    = read_audit_events(code)
        revealed        = any(e.get("type") == "identity_revealed" for e in audit_events)
        current_grading = {}
        grading_history = []

    # Embed the report via iframe
    report_iframe_src = (
        f"/report-raw?code={quote(code, safe='')}&cid={quote(cid, safe='')}"
        if cid else
        f"/report-raw?code={quote(code, safe='')}"
    )
    report_iframe = (
        f'<iframe src="{report_iframe_src}"'
        f' style="width:100%;height:600px;border:none;border-radius:8px;background:#111"></iframe>'
    )

    # Comments section
    comments_html = ""
    for c in raw_comments:
        ts = escape(c.get("created_at") or c.get("timestamp_iso", ""))
        author = escape(c.get("author", "HM"))
        text = escape(c.get("text", ""))
        comments_html += f"""
        <div class="comment">
          <div class="comment-meta">{author} · {ts}</div>
          <div class="comment-text">{text}</div>
        </div>"""
    if not comments_html:
        comments_html = '<div class="no-comments">No comments yet.</div>'

    # Decision section
    decision_html = ""
    if decision_obj:
        d = decision_obj.get("decision", "")
        recorded = escape(decision_obj.get("recorded_at") or decision_obj.get("timestamp_iso", ""))
        colors = {"hire": "#22c55e", "next_round": "#60a5fa", "reject": "#ef4444"}
        labels_map = {"hire": "✓ Hired", "next_round": "→ Next Round", "reject": "✗ Rejected"}
        decision_label = escape(labels_map.get(d, d))
        decision_reason = escape(decision_obj.get("reason", "—"))
        decision_html = f"""
        <div class="current-decision" style="color:{colors.get(d,'#888')}">
          Current decision: <strong>{decision_label}</strong>
          <span style="color:#555;font-size:12px;margin-left:12px">{recorded}</span>
        </div>
        <div style="color:#888;font-size:13px;margin-top:8px">Reason: {decision_reason}</div>"""

    # Audit trail
    audit_rows = ""
    for e in audit_events:
        etype = e.get("type", "")
        ts = escape(e.get("ts") or e.get("timestamp_iso", ""))
        h = escape(e.get("hash", "")[:8])
        color_map = {
            "grade_recorded":     "#fbbf24",
            "grade_revised":      "#f97316",
            "identity_revealed":  "#60a5fa",
            "comment_added":      "#a78bfa",
            "decision_recorded":  "#4ade80",
            "next_round_scheduled": "#60a5fa",
        }
        color = color_map.get(etype, "#555")
        audit_rows += (
            f'<div class="audit-row">'
            f'<span style="color:{color}">{escape(etype)}</span>'
            f'<span class="audit-ts">{ts}</span>'
            f'<span class="audit-hash">{h}</span>'
            f'</div>'
        )

    # Reveal delta
    if relay_session:
        reveal_delta = ""
        for e in audit_events:
            if e.get("type") == "identity_revealed":
                reveal_delta = escape(e.get("delta", ""))
                break
    else:
        reveal_delta = escape(get_reveal_delta(code)) if audit_events else ""

    # Grade panel (relay mode — when we have grading data)
    grade_panel_html = ""
    if graded and current_grading:
        current_score   = current_grading.get("overall_score")
        current_summary = escape(current_grading.get("summary", ""))
        score_display   = f"{current_score} / 10" if current_score is not None else "—"

        # Latest revision info (most recent history entry = previous grade)
        revision_badge = ""
        revision_reason_html = ""
        if grading_history:
            prev = grading_history[-1]
            prev_score = prev.get("overall_score")
            rev_reason = escape(prev.get("revision_reason", ""))
            if prev_score is not None:
                revision_badge = f' <span style="font-size:12px;color:#888">(revised from {prev_score})</span>'
            if rev_reason:
                revision_reason_html = (
                    f'<div style="font-size:12px;color:#888;margin-top:4px">'
                    f'Reason: <em>"{rev_reason}"</em></div>'
                )

        # Revision history entries (all but the latest are older revisions)
        history_rows = ""
        if len(grading_history) > 0:
            for i, h in enumerate(reversed(grading_history)):
                h_score  = h.get("overall_score", "—")
                h_ts     = escape(h.get("superseded_at") or h.get("graded_at", ""))
                h_reason = escape(h.get("revision_reason", ""))
                label    = "Initial grade" if i == len(grading_history) - 1 else f"Revision {len(grading_history) - i - 1}"
                history_rows += (
                    f'<div style="display:grid;grid-template-columns:100px 60px 1fr;'
                    f'gap:6px;font-size:11px;padding:4px 0;border-bottom:1px solid #1a1a1a">'
                    f'<span style="color:#555">{label}</span>'
                    f'<span style="color:#ccc">{h_score} / 10</span>'
                    f'<span style="color:#555">{h_ts[:16].replace("T"," ")}</span>'
                    f'</div>'
                    + (f'<div style="font-size:11px;color:#555;padding-bottom:4px">'
                       f'Reason: {h_reason}</div>' if h_reason else "")
                )
            history_section = (
                f'<details style="margin-top:12px">'
                f'<summary style="font-size:12px;color:#555;cursor:pointer">'
                f'Revision history ({len(grading_history)})</summary>'
                f'<div style="margin-top:8px">{history_rows}</div>'
                f'</details>'
            )
        else:
            history_section = ""

        revise_score_val = current_score if current_score is not None else ""
        grade_panel_html = f"""
    <div class="panel" id="grade-panel">
      <div class="section-title">Grade</div>
      <div style="font-size:22px;font-weight:700;color:#fbbf24;margin-bottom:4px">
        {score_display}{revision_badge}
      </div>
      {revision_reason_html}
      {f'<div style="font-size:12px;color:#555;margin-top:8px">{current_summary}</div>' if current_summary else ''}
      {history_section}
      <div style="margin-top:14px">
        <button class="btn btn-sm" id="btn-toggle-revise" style="border-color:#854d0e;color:#fbbf24">
          Revise Grade
        </button>
      </div>
      <div id="revise-form" style="display:none;margin-top:14px;border-top:1px solid #1a1a1a;padding-top:14px">
        <label style="font-size:12px;color:#888;display:block;margin-bottom:4px">New overall score (0–10)</label>
        <input type="number" id="revise-score" min="0" max="10" step="0.1" value="{revise_score_val}"
               style="width:90px;background:#0a0a0a;border:1px solid #333;color:#e0e0e0;
                      border-radius:6px;padding:6px 10px;font-size:14px;margin-bottom:10px">
        <label style="font-size:12px;color:#888;display:block;margin-bottom:4px">
          Reason for revision <span style="color:#ef4444">*</span>
        </label>
        <textarea id="revise-reason" placeholder="What changed in your evaluation?"
                  style="width:100%;background:#0a0a0a;border:1px solid #333;color:#e0e0e0;
                         border-radius:6px;padding:8px;font-size:12px;min-height:64px;resize:vertical"></textarea>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="btn btn-sm" id="btn-submit-revision"
                  data-code="{escape(code)}" data-cid="{escape(cid)}"
                  style="border-color:#854d0e;color:#fbbf24">Submit Revision</button>
          <button class="btn btn-sm" id="btn-cancel-revision">Cancel</button>
        </div>
        <div id="revise-error" style="display:none;font-size:12px;color:#ef4444;margin-top:6px"></div>
      </div>
    </div>"""

    # Sharing config (relay mode only)
    sharing_panel_html = ""
    if get_relay_url():
        try:
            from interview.core.transport import get_hm_key, get_relay_api_key
            import urllib.request as _ureq
            relay_url_val = get_relay_url()
            token = get_hm_key() or get_relay_api_key()
            sharing_req = _ureq.Request(
                f"{relay_url_val}/sessions/{code}/{cid}/sharing",
                headers={"Authorization": f"Bearer {token}"} if token else {},
            )
            with _ureq.urlopen(sharing_req, timeout=5) as resp:
                sharing_data = json.loads(resp.read()).get("sharing", {})
        except Exception:
            sharing_data = {"score": "none"}

        score_level = escape(sharing_data.get("score", "none"))
        sharing_panel_html = f"""
    <div class="panel" id="sharing-panel">
      <div class="section-title">Candidate Score Sharing
        <span style="color:#555;font-size:10px;font-weight:400"> — what candidates see via <code>interview score {escape(code)}</code></span>
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;color:#888;display:block;margin-bottom:6px">Score detail level</label>
        <select id="sharing-score" style="background:#1a1a1a;border:1px solid #333;color:#ccc;padding:6px 10px;border-radius:6px;font-size:13px">
          <option value="none" {'selected' if score_level == 'none' else ''}>None — candidates see nothing</option>
          <option value="overall" {'selected' if score_level == 'overall' else ''}>Overall score only</option>
          <option value="breakdown" {'selected' if score_level == 'breakdown' else ''}>Score breakdown by dimension</option>
          <option value="breakdown_notes" {'selected' if score_level == 'breakdown_notes' else ''}>Breakdown + HM notes</option>
        </select>
      </div>
      <p style="font-size:12px;color:#555;margin-bottom:12px">Claude's session debrief is always shared with candidates automatically — it's Claude's analysis of the session, not the HM's evaluation.</p>
      <button class="btn btn-sm" id="btn-save-sharing" data-code="{escape(code)}">Save sharing settings</button>
      <span id="sharing-saved" style="display:none;font-size:12px;color:#4ade80;margin-left:10px">Saved.</span>
    </div>"""

    safe_code = escape(code)
    safe_cid = escape(cid) if cid else ""
    # Use JSON encoding for JS string literals to prevent JS injection
    js_code = json.dumps(code)
    js_cid  = json.dumps(cid)
    cid_attr = f'data-cid="{safe_cid}"' if cid else ""

    # Extract identity fields from relay session (only populated after reveal)
    revealed_email    = relay_session.get("candidate_email", "") if relay_session else ""
    revealed_name     = relay_session.get("candidate_name", "")  if relay_session else ""
    revealed_username = relay_session.get("github_username", "")  if relay_session else ""
    revealed_repo_url = relay_session.get("github_repo_url", "")  if relay_session else ""
    revealed_avatar   = relay_session.get("avatar_url", "")       if relay_session else ""

    if revealed:
        # Pre-build HTML fragments (no backslashes in f-string expressions — Python 3.10+)
        onerror_attr = "onerror=\"this.style.display='none'\""
        avatar_html = (
            '<img src="' + escape(revealed_avatar) + '" style="width:48px;height:48px;'
            'border-radius:50%;flex-shrink:0" ' + onerror_attr + '>'
            if revealed_avatar else ''
        )
        name_html = (
            '<div style="font-size:14px;font-weight:600;color:#e0e0e0;margin-bottom:2px">'
            + escape(revealed_name) + '</div>'
            if revealed_name else ''
        )
        email_html = (
            '<div style="font-size:13px;color:#888;margin-bottom:4px">'
            + escape(revealed_email) + '</div>'
            if revealed_email else ''
        )
        gh_user_html = (
            '<div style="font-size:12px;margin-bottom:4px"><a href="https://github.com/'
            + escape(revealed_username) + '" target="_blank" style="color:#60a5fa;text-decoration:none">@'
            + escape(revealed_username) + '</a></div>'
            if revealed_username else ''
        )
        repo_html = (
            '<div style="font-size:12px"><a href="' + escape(revealed_repo_url)
            + '" target="_blank" style="color:#4ade80;text-decoration:none">View code repository →</a></div>'
            if revealed_repo_url else ''
        )
        safe_reveal_delta = escape(reveal_delta)
        identity_block = f"""
      <div style="display:flex;align-items:flex-start;gap:14px;margin-bottom:12px">
        {avatar_html}
        <div style="min-width:0">
          {name_html}
          {email_html}
          {gh_user_html}
          {repo_html}
        </div>
      </div>
      <div class="reveal-note">✓ Blind grading confirmed — {safe_reveal_delta}</div>"""
        identity_panel = f'<div class="panel"><div class="section-title">Identity</div>{identity_block}</div>'
    else:
        # Not yet revealed — show reveal button (locked until graded)
        identity_panel = (
            '<div class="panel"><div class="section-title">Identity</div>'
            + ('<button class="btn btn-sm" id="btn-reveal-detail" data-code="' + safe_code + '" '
               + (f'data-cid="{safe_cid}"' if cid else '')
               + ' ' + ('disabled title="Grade first to unlock Reveal"' if not graded else '')
               + '>Reveal Identity' + (' 🔒' if not graded else '') + '</button>'
               + ('<div style="font-size:11px;color:#555;margin-top:8px">Reveal is locked until a grade is saved. This ensures blind evaluation is preserved in the audit trail.</div>' if not graded else ''))
            + '</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Candidate — {safe_code}</title>
<style>
  {SHARED_CSS}
  .layout {{ display: grid; grid-template-columns: 1fr 340px; gap: 24px; }}
  .panel {{ background: #111; border: 1px solid #222; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
  .comment {{ border-bottom: 1px solid #1a1a1a; padding: 10px 0; }}
  .comment:last-child {{ border-bottom: none; }}
  .comment-meta {{ font-size: 11px; color: #555; margin-bottom: 4px; }}
  .comment-text {{ font-size: 13px; color: #ccc; }}
  .no-comments {{ color: #555; font-size: 13px; }}
  textarea {{ width: 100%; background: #0a0a0a; border: 1px solid #333; color: #e0e0e0;
              border-radius: 6px; padding: 10px; font-size: 13px; resize: vertical;
              min-height: 80px; margin-top: 12px; }}
  textarea:focus {{ outline: none; border-color: #555; }}
  .decision-btns {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
  .current-decision {{ font-size: 14px; font-weight: 600; margin-bottom: 8px; }}
  .audit-row {{ display: grid; grid-template-columns: 1fr 160px 80px; font-size: 11px;
                font-family: monospace; padding: 4px 0; border-bottom: 1px solid #1a1a1a; }}
  .audit-ts {{ color: #555; }}
  .audit-hash {{ color: #333; }}
  .reveal-note {{ font-size: 12px; color: #888; margin-top: 8px; padding: 8px 12px;
                  background: #0d1f0d; border: 1px solid #166534; border-radius: 6px; }}
  .back-link {{ color: #60a5fa; text-decoration: none; font-size: 13px; margin-bottom: 24px; display: block; }}
  .reason-input {{ width: 100%; margin-top: 8px; background: #0a0a0a; border: 1px solid #333;
                   color: #e0e0e0; border-radius: 6px; padding: 8px; font-size: 13px; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>interviewsignal</h1>
  <span class="tagline">{safe_code}</span>
  <a href="/">← Dashboard</a>
</div>
<div class="main">
<a href="/" class="back-link">← All candidates</a>

<div class="layout">
  <div>
    <div class="panel">
      <div class="section-title">Session Report</div>
      {report_iframe}
    </div>
  </div>

  <div>
    <!-- Comments -->
    <div class="panel">
      <div class="section-title">Comments <span style="color:#555;font-size:10px">(append-only · audited)</span></div>
      <div id="comments-list">{comments_html}</div>
      <textarea id="comment-input" placeholder="Add a note... (cannot be edited or deleted)"></textarea>
      <button class="btn btn-sm" style="margin-top:8px" id="btn-add-comment" data-code="{safe_code}" {cid_attr}>Add Comment</button>
    </div>

    <!-- Decision -->
    <div class="panel">
      <div class="section-title">Decision</div>
      {'<div style="color:#f59e0b;font-size:12px;margin-bottom:12px">⚠ Grade this candidate before recording a decision.</div>' if not graded else ''}
      <div id="decision-display">{decision_html}</div>
      <input class="reason-input" id="decision-reason" placeholder="Reason (optional but recommended)">
      <div class="decision-btns">
        <button class="btn btn-sm btn-hire" id="btn-hire" data-code="{safe_code}" {cid_attr} {'disabled' if not graded else ''}>✓ Hire</button>
        <button class="btn btn-sm btn-next" id="btn-next" data-code="{safe_code}" {cid_attr} {'disabled' if not graded else ''}>→ Next Round</button>
        <button class="btn btn-sm btn-reject" id="btn-reject" data-code="{safe_code}" {cid_attr} {'disabled' if not graded else ''}>✗ Reject</button>
      </div>
    </div>

    <!-- Identity / Reveal -->
    {identity_panel}

    <!-- Audit trail -->
    <div class="panel">
      <div class="section-title">Audit Trail <a href="/audit?code={quote(code, safe='')}" style="font-size:10px;color:#444;font-weight:400;float:right">full log ↗</a></div>
      {audit_rows if audit_rows else '<div style="color:#555;font-size:12px">No HM actions recorded yet.</div>'}
    </div>

    <!-- Session integrity -->
    <div class="panel">
      <div class="section-title">Session Integrity</div>
      <div style="font-size:12px;color:#555;margin-bottom:10px">
        Verify the candidate's session log hasn't been tampered with.
        Each event is SHA-256 hash-chained — any edit breaks the chain.
      </div>
      <button class="btn btn-sm" id="btn-verify" data-code="{safe_code}" {cid_attr}>Verify Chain</button>
      <div id="verify-result" style="margin-top:12px;font-size:12px;display:none"></div>
    </div>

    {grade_panel_html}

    {sharing_panel_html}
  </div>
</div>

</div>
<script>
  const _code = {js_code};
  const _cid  = {js_cid};

  document.getElementById('btn-add-comment')?.addEventListener('click', function() {{
    const text = document.getElementById('comment-input').value.trim();
    if (!text) {{ alert('Comment cannot be empty.'); return; }}
    fetch('/add-comment', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{code: _code, cid: _cid, text}})}})
      .then(r => r.json()).then(d => {{
        if (d.ok) {{ location.reload(); }}
        else {{ alert('Error: ' + d.error); }}
      }});
  }});

  ['btn-hire','btn-next','btn-reject'].forEach(id => {{
    document.getElementById(id)?.addEventListener('click', function() {{
      const decision = {{'btn-hire':'hire','btn-next':'next_round','btn-reject':'reject'}}[id];
      const reason = document.getElementById('decision-reason').value.trim();
      if (!confirm('Record decision: ' + decision.toUpperCase() + '?\\nThis will be audit-logged.')) return;
      fetch('/record-decision', {{method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{code: _code, cid: _cid, decision, reason}})}})
        .then(r => r.json()).then(d => {{
          if (d.ok) {{ location.reload(); }}
          else {{ alert('Error: ' + d.error); }}
        }});
    }});
  }});

  document.getElementById('btn-reveal-detail')?.addEventListener('click', function() {{
    if (this.disabled) return;
    fetch('/reveal', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{code: _code, cid: _cid}})}})
      .then(r => r.json()).then(d => {{ location.reload(); }});
  }});

  document.getElementById('btn-toggle-revise')?.addEventListener('click', function() {{
    const form = document.getElementById('revise-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
  }});
  document.getElementById('btn-cancel-revision')?.addEventListener('click', function() {{
    document.getElementById('revise-form').style.display = 'none';
    document.getElementById('revise-error').style.display = 'none';
  }});
  document.getElementById('btn-submit-revision')?.addEventListener('click', function() {{
    const code   = this.dataset.code;
    const cid    = this.dataset.cid;
    const score  = parseFloat(document.getElementById('revise-score').value);
    const reason = document.getElementById('revise-reason').value.trim();
    const errDiv = document.getElementById('revise-error');
    if (isNaN(score) || score < 0 || score > 10) {{
      errDiv.textContent = 'Score must be a number between 0 and 10.';
      errDiv.style.display = 'block'; return;
    }}
    if (!reason) {{
      errDiv.textContent = 'Reason is required.';
      errDiv.style.display = 'block'; return;
    }}
    errDiv.style.display = 'none';
    this.disabled = true;
    this.textContent = 'Submitting...';
    const btn = this;
    fetch('/revise-grade', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{code, cid, overall_score: score, reason}})}})
      .then(r => r.json()).then(d => {{
        if (d.ok) {{ location.reload(); }}
        else {{
          errDiv.textContent = 'Error: ' + d.error;
          errDiv.style.display = 'block';
          btn.disabled = false;
          btn.textContent = 'Submit Revision';
        }}
      }}).catch(e => {{
        errDiv.textContent = 'Request failed: ' + e;
        errDiv.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Submit Revision';
      }});
  }});

  document.getElementById('btn-save-sharing')?.addEventListener('click', function() {{
    const code  = this.dataset.code;
    const score = document.getElementById('sharing-score').value;
    fetch('/update-sharing', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{code, sharing: {{score}}}})
    }}).then(r => r.json()).then(d => {{
      if (d.ok) {{
        const saved = document.getElementById('sharing-saved');
        saved.style.display = 'inline';
        setTimeout(() => {{ saved.style.display = 'none'; }}, 2000);
      }} else {{
        alert('Error saving sharing settings: ' + d.error);
      }}
    }});
  }});

  document.getElementById('btn-verify')?.addEventListener('click', function() {{
    const btn = this;
    const out = document.getElementById('verify-result');
    btn.disabled = true;
    btn.textContent = 'Verifying...';
    out.style.display = 'none';
    const qs = _cid ? `?code=${{_code}}&cid=${{_cid}}` : `?code=${{_code}}`;
    fetch('/verify' + qs)
      .then(r => r.json())
      .then(d => {{
        btn.disabled = false;
        btn.textContent = 'Verify Chain';
        out.style.display = 'block';

        const ok = d.ok;
        const color = ok ? '#22c55e' : '#ef4444';
        const icon  = ok ? '✓' : '✗';

        const fmt = ts => {{
          if (!ts) return '—';
          if (typeof ts === 'string') return ts.replace('T',' ').replace('Z','');
          return new Date(ts * 1000).toISOString().replace('T',' ').replace('Z','').slice(0,19);
        }};

        let rows = `
          <div style="color:${{color}};font-weight:600;margin-bottom:8px">${{icon}} ${{d.details}}</div>
          <div style="display:grid;grid-template-columns:120px 1fr;gap:4px;color:#888">
            <span>Events</span><span style="color:#ccc">${{d.event_count}}</span>
            <span>Chain</span><span style="color:${{d.chain_intact ? '#22c55e' : '#ef4444'}}">${{d.chain_intact ? 'intact' : 'BROKEN'}}</span>
            <span>Manifest</span><span style="color:${{d.manifest_ok ? '#22c55e' : '#ef4444'}}">${{d.manifest_ok ? 'ok' : 'MISMATCH'}}</span>
            <span>Started</span><span style="color:#ccc">${{fmt(d.session_start)}}</span>
            <span>Ended</span><span style="color:#ccc">${{fmt(d.session_end)}}</span>
            <span>Duration</span><span style="color:#ccc">${{d.elapsed_minutes != null ? d.elapsed_minutes + ' min' : '—'}}</span>`;
        if (d.submitted_at) {{
          rows += `<span>Submitted</span><span style="color:#ccc">${{fmt(d.submitted_at)}}</span>`;
        }}
        rows += `
            <span>Final hash</span><span style="color:#444;font-family:monospace;font-size:10px">${{d.final_hash}}</span>
            <span>Verified at</span><span style="color:#444">${{d.verified_at}}</span>
          </div>`;
        out.innerHTML = rows;
      }})
      .catch(e => {{
        btn.disabled = false;
        btn.textContent = 'Verify Chain';
        out.style.display = 'block';
        out.innerHTML = '<span style="color:#ef4444">Request failed: ' + e + '</span>';
      }});
  }});
</script>
</body>
</html>"""


def _build_audit_log_html(code: str | None = None) -> str:
    """Full audit log viewer — all events or filtered to one interview."""
    from interview.core.audit import read_events, verify_chain

    events = read_events(code)
    ok, msg = verify_chain()

    rows = ""
    for e in events:
        etype = escape(e["type"])
        ts = escape(e.get("timestamp_iso", ""))
        ecode_raw = e.get("code", "")
        ecode = escape(ecode_raw)
        h = escape(e.get("hash", ""))
        prev = escape(e.get("prev_hash", "")[:8])
        payload_str = escape(json.dumps(e.get("payload", {}))[:120])
        color_map = {
            "grade_recorded":     "#fbbf24", "grade_revised": "#f97316",
            "identity_revealed":  "#60a5fa",
            "comment_added":      "#a78bfa", "decision_recorded": "#4ade80",
            "next_round_scheduled": "#60a5fa", "report_opened": "#555",
        }
        color = color_map.get(e["type"], "#555")
        rows += f"""<tr>
          <td style="color:{color};font-weight:600">{etype}</td>
          <td><a href="/candidate?code={quote(ecode_raw, safe='')}" style="color:#60a5fa;text-decoration:none">{ecode}</a></td>
          <td style="color:#888">{ts}</td>
          <td style="color:#444;font-size:11px">{prev}…→{h[:8]}</td>
          <td style="color:#555;font-size:11px;font-family:monospace">{payload_str}</td>
        </tr>"""

    integrity_color = "#22c55e" if ok else "#ef4444"
    integrity_icon = "✓" if ok else "✗"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Audit Log — interviewsignal</title>
<style>
  {SHARED_CSS}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ text-align: left; color: #555; font-size: 11px; text-transform: uppercase;
        letter-spacing: 0.06em; padding: 8px 12px; border-bottom: 1px solid #222; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #111; vertical-align: top; }}
  .integrity {{ padding: 12px 20px; border-radius: 8px; margin-bottom: 24px;
                border: 1px solid; font-size: 13px; }}
  .integrity.ok {{ background: #0d1f0d; border-color: #166534; color: #4ade80; }}
  .integrity.fail {{ background: #1f0d0d; border-color: #7f1d1d; color: #f87171; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>interviewsignal</h1>
  <span class="tagline">Audit Log{' — ' + code if code else ''}</span>
  <a href="/">← Dashboard</a>
</div>
<div class="main">
  <div class="integrity {'ok' if ok else 'fail'}">
    {integrity_icon} Chain integrity: {msg}
  </div>
  {'<p style="color:#555;font-size:13px;padding:32px 0">No audit events recorded yet.</p>' if not events else
   '<table><thead><tr><th>Event</th><th>Interview</th><th>Timestamp</th><th>Hash chain</th><th>Payload</th></tr></thead><tbody>' + rows + '</tbody></table>'}
</div>
</body>
</html>"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress request logs

    def _send_html(self, html: str, status=200):
        encoded = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(encoded))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, data: dict, status=200):
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(encoded))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        from interview.core import audit as audit_mod
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/dashboard":
            reports = _load_all_reports()
            self._send_html(_build_dashboard_html(reports))

        elif path == "/candidate":
            code = params.get("code", [""])[0]
            cid  = params.get("cid", [""])[0]
            if not code:
                self._send_html("<p>No code specified.</p>", 400)
                return
            # Log report_opened audit event (once per session via simple dedup)
            existing = audit_mod.read_events(code)
            if not any(e["type"] == "report_opened" for e in existing):
                audit_mod.append("report_opened", code, {})
            self._send_html(_build_candidate_detail_html(code, cid))

        elif path == "/report-raw":
            code = params.get("code", [""])[0]
            cid  = params.get("cid", [""])[0]
            report_file = SESSIONS_DIR / code / "report.html"
            if report_file.exists():
                self._send_html(report_file.read_text())
            elif get_relay_url():
                try:
                    from interview.core.transport import get_hm_key, get_relay_api_key
                    relay_url = get_relay_url()
                    token = get_hm_key() or get_relay_api_key()
                    rpath = (
                        f"/sessions/{code}/{cid}/report.html"
                        if cid else f"/sessions/{code}/report.html"
                    )
                    req = urllib.request.Request(
                        f"{relay_url}{rpath}",
                        headers={"Authorization": f"Bearer {token}"} if token else {},
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        self._send_html(resp.read().decode())
                except Exception:
                    self._send_html(
                        "<p style='color:#555;padding:32px;font-family:sans-serif'>"
                        "Report not available.</p>"
                    )
            else:
                self._send_html(
                    "<p style='color:#555;padding:32px;font-family:sans-serif'>"
                    "Report not yet generated. Run /submit to generate it.</p>"
                )

        elif path == "/verify":
            code = params.get("code", [""])[0]
            cid  = params.get("cid", [""])[0]
            if not code:
                self._send_json({"error": "Missing code"}, 400)
                return
            # Ensure events.jsonl is cached locally before verifying
            _ensure_local_cache(code, cid)
            from interview.core.integrity import verify_session
            result = verify_session(code)
            # Attach relay submission timestamp if available
            if get_relay_url() and cid:
                transport = get_transport()
                relay_session = transport.get_session(code, cid)
                if relay_session:
                    result["submitted_at"] = relay_session.get("submitted_at")
                    result["graded_at"]    = relay_session.get("graded_at")
            self._send_json(result)

        elif path == "/audit":
            code = params.get("code", [""])[0] or None
            self._send_html(_build_audit_log_html(code))

        else:
            self._send_html("<p>Not found.</p>", 404)

    def do_POST(self):
        from interview.core import audit as audit_mod
        from interview.core.decisions import (
            add_comment, record_decision, record_reveal, save_grade
        )
        parsed = urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/grade":
            # Accept entries=[{code, cid}] (relay mode) or codes=[...] (legacy)
            entries = body.get("entries", [])
            if not entries and body.get("codes"):
                entries = [{"code": c, "cid": ""} for c in body["codes"]]
            results = []
            for entry in entries:
                code = entry.get("code", "")
                cid  = entry.get("cid", "")
                try:
                    _run_grading(code, cid)
                    results.append({"code": code, "status": "graded"})
                except Exception as e:
                    results.append({"code": code, "status": "error", "error": str(e)})
            succeeded = sum(1 for r in results if r["status"] == "graded")
            self._send_json({
                "message": f"Graded {succeeded}/{len(entries)} candidates. Refresh to see scores.",
                "results": results,
            })

        elif path == "/reveal":
            code = body.get("code", "")
            cid  = body.get("cid", "")
            if not code:
                self._send_json({"error": "Missing code"}, 400)
                return
            transport = get_transport()
            try:
                result = transport.post_action(code, "reveal", {}, cid=cid or None)
                self._send_json({
                    "code":            code,
                    "candidate_email": result.get("candidate_email", ""),
                    "delta":           result.get("delta", ""),
                })
            except Exception as e:
                self._send_json({"error": str(e)}, 400)

        elif path == "/add-comment":
            code = body.get("code", "")
            cid  = body.get("cid", "")
            text = body.get("text", "").strip()
            if not code or not text:
                self._send_json({"ok": False, "error": "Missing code or text"}, 400)
                return
            transport = get_transport()
            try:
                comment = transport.post_action(code, "comment", {"text": text}, cid=cid or None)
                self._send_json({"ok": True, "comment": comment})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 400)

        elif path == "/record-decision":
            code     = body.get("code", "")
            cid      = body.get("cid", "")
            decision = body.get("decision", "")
            reason   = body.get("reason", "")
            if not code or not decision:
                self._send_json({"ok": False, "error": "Missing code or decision"}, 400)
                return
            transport = get_transport()
            try:
                record = transport.post_action(
                    code, "decision", {"decision": decision, "reason": reason},
                    cid=cid or None,
                )
                self._send_json({"ok": True, "record": record})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 400)

        elif path == "/revise-grade":
            code   = body.get("code", "")
            cid    = body.get("cid", "")
            reason = body.get("reason", "").strip()
            new_overall = body.get("overall_score")
            if not code or not cid or not reason or new_overall is None:
                self._send_json({"ok": False, "error": "Missing code, cid, overall_score, or reason"}, 400)
                return
            if not get_relay_url():
                self._send_json({"ok": False, "error": "Grade revision requires a relay."}, 400)
                return
            try:
                from interview.core.transport import get_hm_key, get_relay_api_key
                relay_url_val = get_relay_url()
                token = get_hm_key() or get_relay_api_key()
                # Fetch current grading to preserve dimensions etc.
                transport = get_transport()
                relay_session = transport.get_session(code, cid)
                if not relay_session:
                    self._send_json({"ok": False, "error": "Session not found."}, 404)
                    return
                current_grading = relay_session.get("grading") or {}
                revised = {
                    **current_grading,
                    "overall_score": float(new_overall),
                    "reason":        reason,
                }
                # Remove graded_at — relay will set a fresh one
                revised.pop("graded_at", None)
                req_body = json.dumps(revised).encode()
                req = urllib.request.Request(
                    f"{relay_url_val}/sessions/{code}/{cid}/grade",
                    data=req_body,
                    headers={
                        "Content-Type":  "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read())
                self._send_json({"ok": True, "result": result})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 400)

        elif path == "/update-sharing":
            code    = body.get("code", "")
            sharing = body.get("sharing", {})
            if not code or not isinstance(sharing, dict):
                self._send_json({"ok": False, "error": "Missing code or sharing config"}, 400)
                return
            if not get_relay_url():
                self._send_json({"ok": False, "error": "Sharing controls require a relay."}, 400)
                return
            try:
                from interview.core.transport import get_hm_key, get_relay_api_key
                relay_url_val = get_relay_url()
                token = get_hm_key() or get_relay_api_key()
                req_body = json.dumps({"sharing": sharing}).encode()
                req = urllib.request.Request(
                    f"{relay_url_val}/sessions/{code}/sharing",
                    data=req_body,
                    headers={
                        "Content-Type":  "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    json.loads(resp.read())
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 400)

        else:
            self._send_json({"error": "Not found"}, 404)


def _run_grading(code: str, cid: str = ""):
    """
    Grade a session using the Anthropic API.

    Relay mode:  downloads events + manifest to local cache, grades locally,
                 then POSTs the result to the relay via transport.post_action().
    Email mode:  grades from local files, saves grading.json locally.
    """
    from interview.core.grader import grade_session, GradingError, _get_api_key

    if not _get_api_key():
        session_dir = SESSIONS_DIR / code
        grading_file = session_dir / "grading.json"
        if not grading_file.exists():
            session_dir.mkdir(parents=True, exist_ok=True)
            grading_file.write_text(json.dumps({
                "code": code,
                "overall_score": None,
                "dimensions": [],
                "summary": (
                    "⚠ No API key configured. "
                    "Run: interview configure-api-key  "
                    "or set ANTHROPIC_API_KEY environment variable."
                ),
                "standout_moments": [],
                "concerns": [],
                "status": "no_api_key",
            }, indent=2))
        raise GradingError("No Anthropic API key. Run: interview configure-api-key")

    # In relay mode, ensure session files are cached locally before grading
    if get_relay_url():
        _ensure_local_cache(code, cid)

    # Grade locally (reads from ~/.interview/sessions/<code>/)
    grading = grade_session(code)  # raises GradingError on failure

    # In relay mode, persist the grade result to the relay
    if get_relay_url():
        transport = get_transport()
        try:
            transport.post_action(code, "grade", grading, cid=cid or None)
        except Exception as e:
            err_str = str(e)
            if "revision_requires_reason" in err_str or "409" in err_str:
                raise GradingError(
                    "This candidate is already graded. Use 'Revise Grade' on their detail "
                    "page to update the score with a reason."
                )
            print(f"  ⚠ Grade saved locally but relay sync failed: {e}")


def start_dashboard():
    ensure_dirs()
    url = f"http://localhost:{PORT}"
    relay = get_relay_url()
    print(f"\n✓ interviewsignal dashboard running at {url}")
    if relay:
        print(f"  Relay:  {relay}")
        print(f"  Mode:   relay — submissions fetched from relay automatically")
    else:
        print(f"  Mode:   email — save report JSON attachments to ~/.interview/received/")
        print(f"  Tip:    run 'interview configure-relay' to connect a relay server")
    print(f"  Press Ctrl+C to stop.\n")
    webbrowser.open(url)

    server = http.server.HTTPServer(("localhost", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")


if __name__ == "__main__":
    start_dashboard()

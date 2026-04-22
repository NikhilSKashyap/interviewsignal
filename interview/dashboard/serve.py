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
                manifest_file = session_dir / "manifest.json"
                if manifest_file.exists():
                    try:
                        manifest: dict = json.loads(manifest_file.read_text())
                        grading_file = session_dir / "grading.json"
                        grading: dict = {}
                        if grading_file.exists():
                            try:
                                grading = json.loads(grading_file.read_text())
                            except Exception:
                                pass
                        session_code = session_dir.name
                        r = {
                            "code":            session_code,
                            "started_at":      manifest.get("started_at"),
                            "ended_at":        manifest.get("ended_at"),
                            "elapsed_minutes": manifest.get("elapsed_minutes"),
                            "overall_score":   grading.get("overall_score"),
                            "event_count":     manifest.get("event_count"),
                            "_source":         "local",
                            "_anonymize":      manifest.get("anonymize", True),
                        }
                        # Load or compute flags for this local session
                        local_flags = _load_local_flags(session_code)
                        r["flag_count"] = len(local_flags)
                        if any(f.get("severity") == "red" for f in local_flags):
                            r["flag_severity"] = "red"
                        elif any(f.get("severity") == "yellow" for f in local_flags):
                            r["flag_severity"] = "yellow"
                        else:
                            r["flag_severity"] = "none"
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
    # Unix timestamp for JS sorting
    submitted_ts = r.get("submitted_at") or r.get("ended_at") or 0
    if isinstance(submitted_ts, str):
        try:
            import datetime
            submitted_ts = datetime.datetime.fromisoformat(
                submitted_ts.replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            submitted_ts = 0
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

    # Determine status for data attribute
    if decision_obj or r.get("decision"):
        row_status = "decided"
    elif graded or (score is not None):
        row_status = "graded"
    else:
        row_status = "pending"

    # Duration as float for sorting (strip " min" suffix if present)
    elapsed_float = 0.0
    try:
        elapsed_float = float(str(elapsed).replace("min", "").strip())
    except Exception:
        pass

    # Flag severity for data attribute
    flag_severity = r.get("flag_severity", "none")

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

    # Flag indicator dot
    flag_count = r.get("flag_count", 0)
    if flag_severity == "red":
        flag_dot_color = "#ef4444"
        flag_title = f"{flag_count} red flag(s)"
    elif flag_severity == "yellow":
        flag_dot_color = "#f59e0b"
        flag_title = f"{flag_count} yellow flag(s)"
    else:
        flag_dot_color = "#22c55e"
        flag_title = "No flags"
    flag_indicator = (
        f'<span title="{flag_title}" style="color:{flag_dot_color};font-size:16px;line-height:1">&#9679;</span>'
    )

    # Graded-by badge (Auto vs HM)
    graded_by = r.get("graded_by", "hm") if r.get("graded") else None
    graded_by_badge = ""
    if graded_by == "auto":
        graded_by_badge = (
            ' <span title="Auto-graded on submission" '
            'style="font-size:10px;color:#60a5fa;background:#0c1a2e;'
            'border:1px solid #1e40af;border-radius:10px;padding:1px 6px;'
            'vertical-align:middle">Auto</span>'
        )
    elif graded_by == "hm" and r.get("graded"):
        graded_by_badge = (
            ' <span title="Graded by hiring manager" '
            'style="font-size:10px;color:#a3a3a3;background:#1a1a1a;'
            'border:1px solid #333;border-radius:10px;padding:1px 6px;'
            'vertical-align:middle">HM</span>'
        )

    score_data = score if score is not None else ""
    return f"""
    <tr data-code="{code}" data-cid="{cid}" data-score="{score_data}" data-submitted="{submitted_ts}" data-duration="{elapsed_float}" data-flag-severity="{flag_severity}" data-status="{row_status}">
      <td class="td-label">
        <input type="checkbox" class="candidate-checkbox" data-code="{code}" data-cid="{cid}">
        <span class="display-label">{label}</span>{decision_badge}
      </td>
      <td><span class="score-badge" style="color:{score_col}">{score_str}</span>{graded_by_badge}</td>
      <td>{flag_indicator}</td>
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
    graded_count = sum(1 for r in reports if r.get("overall_score") is not None)
    avg_score_val = round(
        sum(r["overall_score"] for r in reports if r.get("overall_score") is not None) / graded_count, 1
    ) if graded_count else None

    # Default sort: score descending if any graded, else submission time descending
    default_sort = "score-desc" if graded_count > 0 else "submitted-desc"

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
  .toolbar {{ display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
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
  /* Sort + filter controls */
  .controls-row {{ display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }}
  .controls-row label {{ font-size: 12px; color: #888; }}
  .ctrl-select {{ background: #1a1a1a; border: 1px solid #333; color: #ccc;
                  padding: 5px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; }}
  .ctrl-input {{ background: #1a1a1a; border: 1px solid #333; color: #ccc;
                 padding: 5px 8px; border-radius: 6px; font-size: 12px; width: 58px; }}
  /* Summary bar */
  .summary-bar {{ background: #111; border: 1px solid #222; border-radius: 6px;
                  padding: 10px 16px; margin-bottom: 10px; font-size: 12px; color: #888;
                  display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }}
  .summary-bar span {{ color: #ccc; }}
  .summary-bar .sep {{ color: #333; }}
  /* Selection count bar */
  .sel-bar {{ background: #0c1a2e; border: 1px solid #1e40af; border-radius: 6px;
              padding: 8px 14px; margin-bottom: 8px; font-size: 12px; color: #93c5fd;
              display: none; }}
  /* Batch actions bar */
  .batch-bar {{ background: #111; border: 1px solid #333; border-radius: 6px;
                padding: 10px 14px; margin-bottom: 10px; display: none;
                gap: 10px; align-items: center; flex-wrap: wrap; }}
  .batch-bar.visible {{ display: flex; }}
  .batch-progress {{ font-size: 12px; color: #888; margin-left: 8px; }}
  /* Pagination */
  .pagination {{ display: flex; gap: 10px; align-items: center; margin-top: 16px;
                 font-size: 13px; color: #888; }}
  .pagination button {{ background: #1a1a1a; border: 1px solid #333; color: #ccc;
                         padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }}
  .pagination button:disabled {{ opacity: 0.3; cursor: not-allowed; }}
  /* Confirmation dialog overlay */
  .confirm-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.7);
                       z-index: 1000; display: flex; align-items: center; justify-content: center; }}
  .confirm-box {{ background: #161616; border: 1px solid #333; border-radius: 10px;
                  padding: 28px 32px; max-width: 420px; width: 90%; }}
  .confirm-box h3 {{ font-size: 15px; color: #fff; margin-bottom: 10px; }}
  .confirm-box p {{ font-size: 13px; color: #888; margin-bottom: 20px; }}
  .confirm-btns {{ display: flex; gap: 10px; }}
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
    <div class="stat"><div class="stat-val">{graded_count}</div><div class="stat-label">Graded</div></div>
    <div class="stat"><div class="stat-val">{avg_score_val if avg_score_val is not None else "—"}</div><div class="stat-label">Avg Score</div></div>
  </div>

  {'<div class="received-hint"><strong>Relay connected.</strong> Submissions appear automatically when candidates run /submit.</div>'
   if get_relay_url() else
   '<div class="received-hint"><strong>To add submissions:</strong> save <code>interview_report_*.json</code> email attachments to <code>~/.interview/received/</code> — they appear here automatically.</div>'}

  <div class="toolbar">
    <button class="btn btn-primary" id="btn-grade-selected">Grade Selected</button>
    <button class="btn" id="btn-grade-all">Grade All</button>
    <button class="btn" onclick="location.reload()">↻ Refresh</button>
  </div>

  {'<div id="candidates-section">' if reports else ''}

  {'<!-- Sort controls -->' if reports else ''}
  {'<div class="controls-row"><label>Sort by:</label><select class="ctrl-select" id="sort-select"><option value="score-desc">Score ↓</option><option value="score-asc">Score ↑</option><option value="submitted-desc">Submitted (newest)</option><option value="submitted-asc">Submitted (oldest)</option><option value="duration">Session duration</option><option value="flags">Flag severity (red first)</option></select></div>' if reports else ''}

  {'<!-- Filter controls -->' if reports else ''}
  {'<div class="controls-row"><label>Status:</label><select class="ctrl-select" id="filter-status"><option value="all">All</option><option value="graded">Graded</option><option value="pending">Pending</option><option value="decided">Decided</option></select><label style="margin-left:8px">Flags:</label><select class="ctrl-select" id="filter-flags"><option value="all">All</option><option value="clean">Clean only</option><option value="flagged">Flagged only</option></select><label style="margin-left:8px">Score:</label><input type="number" class="ctrl-input" id="filter-score-min" min="0" max="10" step="0.1" placeholder="min"><span style="color:#555;font-size:12px">–</span><input type="number" class="ctrl-input" id="filter-score-max" min="0" max="10" step="0.1" placeholder="max"><button class="btn btn-sm" id="btn-apply-filter" style="margin-left:4px">Apply</button></div>' if reports else ''}

  {'<!-- Summary bar -->' if reports else ''}
  {'<div class="summary-bar" id="summary-bar"><span id="sb-total">0 submissions</span><span class="sep">|</span><span id="sb-graded">0 graded</span><span class="sep">|</span><span id="sb-pending">0 pending</span><span class="sep">|</span><span id="sb-avg">avg score —</span><span class="sep">|</span><span id="sb-advancing">0 advancing</span><span class="sep">|</span><span id="sb-rejected">0 rejected</span></div>' if reports else ''}

  {'<!-- Selection count bar -->' if reports else ''}
  {'<div class="sel-bar" id="sel-bar">0 selected</div>' if reports else ''}

  {'<!-- Batch actions bar -->' if reports else ''}
  {'<div class="batch-bar" id="batch-bar"><button class="btn btn-sm btn-grade" id="batch-grade">Grade Selected</button><button class="btn btn-sm btn-next" id="batch-advance">Advance Selected</button><button class="btn btn-sm btn-reject" id="batch-reject">Reject Selected</button><span style="margin-left:8px;color:#555;font-size:12px">|</span><label style="font-size:12px;color:#888;margin-left:8px">Reject below score:</label><input type="number" class="ctrl-input" id="batch-threshold" min="0" max="10" step="0.1" placeholder="e.g. 5"><button class="btn btn-sm btn-reject" id="batch-reject-below" style="margin-left:4px">Reject Below</button><span class="batch-progress" id="batch-progress"></span></div>' if reports else ''}

  {'<table id="candidates-table"><thead><tr><th><input type="checkbox" id="select-all"> Candidate</th><th>Score</th><th>Flags</th><th>Duration</th><th>Events</th><th>Submitted</th><th>Actions</th></tr></thead><tbody id="candidates-tbody">' + rows + '</tbody></table>'
   if reports else
   '<div class="empty"><h3>No submissions yet.</h3><p>Candidates appear here after /submit.</p></div>'}

  {'<!-- Pagination -->' if reports else ''}
  {'<div class="pagination" id="pagination-bar"><button id="btn-prev-page" disabled>← Prev</button><span id="page-label"></span><button id="btn-next-page" disabled>Next →</button></div>' if reports else ''}

  {'</div>' if reports else ''}

</div>

<!-- Confirmation dialog (hidden) -->
<div class="confirm-overlay" id="confirm-overlay" style="display:none">
  <div class="confirm-box">
    <h3 id="confirm-title">Are you sure?</h3>
    <p id="confirm-msg">This action cannot be undone.</p>
    <div class="confirm-btns">
      <button class="btn btn-primary" id="confirm-ok">Confirm</button>
      <button class="btn" id="confirm-cancel">Cancel</button>
    </div>
  </div>
</div>

<script>
(function() {{
  // ── Constants ──────────────────────────────────────────────────────────────
  const PAGE_SIZE = 50;
  let currentPage = 1;

  // ── Row references ─────────────────────────────────────────────────────────
  const tbody = document.getElementById('candidates-tbody');
  if (!tbody) return; // No candidates — nothing to do

  const allRows = Array.from(tbody.querySelectorAll('tr'));

  // Rows that survive current filter (updated by applyFilterAndSort)
  let visibleRows = allRows.slice();

  // ── Sort ───────────────────────────────────────────────────────────────────
  const sortSelect = document.getElementById('sort-select');
  sortSelect.value = '{default_sort}';

  function sortRows(rows, key) {{
    const flagOrder = {{ none: 0, yellow: 1, red: 2 }};
    return rows.slice().sort((a, b) => {{
      switch (key) {{
        case 'score-desc': {{
          const sa = a.dataset.score !== '' ? parseFloat(a.dataset.score) : -1;
          const sb = b.dataset.score !== '' ? parseFloat(b.dataset.score) : -1;
          return sb - sa;
        }}
        case 'score-asc': {{
          const sa = a.dataset.score !== '' ? parseFloat(a.dataset.score) : 99;
          const sb = b.dataset.score !== '' ? parseFloat(b.dataset.score) : 99;
          return sa - sb;
        }}
        case 'submitted-desc':
          return parseFloat(b.dataset.submitted || 0) - parseFloat(a.dataset.submitted || 0);
        case 'submitted-asc':
          return parseFloat(a.dataset.submitted || 0) - parseFloat(b.dataset.submitted || 0);
        case 'duration':
          return parseFloat(b.dataset.duration || 0) - parseFloat(a.dataset.duration || 0);
        case 'flags': {{
          const fa = flagOrder[a.dataset.flagSeverity] ?? 0;
          const fb = flagOrder[b.dataset.flagSeverity] ?? 0;
          return fb - fa;
        }}
        default:
          return 0;
      }}
    }});
  }}

  // ── Filter ─────────────────────────────────────────────────────────────────
  const filterStatus = document.getElementById('filter-status');
  const filterFlags  = document.getElementById('filter-flags');
  const scoreMin     = document.getElementById('filter-score-min');
  const scoreMax     = document.getElementById('filter-score-max');

  function filterRows(rows) {{
    const status  = filterStatus.value;
    const flags   = filterFlags.value;
    const minVal  = scoreMin.value !== '' ? parseFloat(scoreMin.value) : null;
    const maxVal  = scoreMax.value !== '' ? parseFloat(scoreMax.value) : null;

    return rows.filter(row => {{
      // Status filter
      if (status !== 'all' && row.dataset.status !== status) return false;
      // Flags filter
      if (flags === 'clean' && row.dataset.flagSeverity !== 'none') return false;
      if (flags === 'flagged' && row.dataset.flagSeverity === 'none') return false;
      // Score range filter
      const score = row.dataset.score !== '' ? parseFloat(row.dataset.score) : null;
      if (minVal !== null && (score === null || score < minVal)) return false;
      if (maxVal !== null && (score === null || score > maxVal)) return false;
      return true;
    }});
  }}

  // ── Summary bar ────────────────────────────────────────────────────────────
  function updateSummaryBar(rows) {{
    const total    = rows.length;
    const graded   = rows.filter(r => r.dataset.status === 'graded' || r.dataset.status === 'decided').length;
    const pending  = rows.filter(r => r.dataset.status === 'pending').length;
    const scores   = rows.map(r => r.dataset.score !== '' ? parseFloat(r.dataset.score) : null).filter(s => s !== null);
    const avg      = scores.length ? (scores.reduce((a,b) => a+b, 0) / scores.length).toFixed(1) : '—';

    // Count decided rows by inspecting decision badge text
    let advancing = 0, rejected = 0;
    rows.forEach(r => {{
      const badge = r.querySelector('.display-label')?.nextElementSibling;
      if (!badge) return;
      const t = badge.textContent || '';
      if (t.includes('Next Round') || t.includes('Hired')) advancing++;
      if (t.includes('Rejected')) rejected++;
    }});

    document.getElementById('sb-total').textContent   = total + ' submission' + (total !== 1 ? 's' : '');
    document.getElementById('sb-graded').textContent  = graded + ' graded';
    document.getElementById('sb-pending').textContent = pending + ' pending';
    document.getElementById('sb-avg').textContent     = 'avg score ' + avg;
    document.getElementById('sb-advancing').textContent = advancing + ' advancing';
    document.getElementById('sb-rejected').textContent  = rejected + ' rejected';
  }}

  // ── Pagination ─────────────────────────────────────────────────────────────
  const btnPrev  = document.getElementById('btn-prev-page');
  const btnNext  = document.getElementById('btn-next-page');
  const pageLabel = document.getElementById('page-label');
  const paginationBar = document.getElementById('pagination-bar');

  function renderPage() {{
    const totalPages = Math.max(1, Math.ceil(visibleRows.length / PAGE_SIZE));
    if (currentPage > totalPages) currentPage = totalPages;

    const start = (currentPage - 1) * PAGE_SIZE;
    const end   = start + PAGE_SIZE;

    // Hide all rows, then show the current page slice of visible rows
    allRows.forEach(r => {{ r.style.display = 'none'; }});
    visibleRows.slice(start, end).forEach(r => {{ r.style.display = ''; }});

    btnPrev.disabled  = currentPage <= 1;
    btnNext.disabled  = currentPage >= totalPages;
    pageLabel.textContent = `Page ${{currentPage}} of ${{totalPages}} (${{visibleRows.length}} candidates)`;

    // Only show pagination bar when needed
    paginationBar.style.display = visibleRows.length > PAGE_SIZE ? 'flex' : 'none';

    updateSelectionCount();
  }}

  btnPrev.addEventListener('click', () => {{ currentPage--; renderPage(); }});
  btnNext.addEventListener('click', () => {{ currentPage++; renderPage(); }});

  // ── Main apply function ────────────────────────────────────────────────────
  function applyFilterAndSort() {{
    currentPage = 1;

    // Filter
    const filtered = filterRows(allRows);

    // Sort
    const sorted = sortRows(filtered, sortSelect.value);

    // Reorder DOM
    sorted.forEach(r => tbody.appendChild(r));
    visibleRows = sorted;

    renderPage();
    updateSummaryBar(visibleRows);
    // Uncheck all when filter changes
    document.getElementById('select-all').checked = false;
    document.querySelectorAll('.candidate-checkbox').forEach(cb => cb.checked = false);
    updateSelectionCount();
  }}

  sortSelect.addEventListener('change', applyFilterAndSort);
  document.getElementById('btn-apply-filter').addEventListener('click', applyFilterAndSort);

  // ── Select all (visible page rows only) ────────────────────────────────────
  document.getElementById('select-all').addEventListener('change', function() {{
    const start = (currentPage - 1) * PAGE_SIZE;
    const end   = start + PAGE_SIZE;
    visibleRows.slice(start, end).forEach(r => {{
      const cb = r.querySelector('.candidate-checkbox');
      if (cb) cb.checked = this.checked;
    }});
    updateSelectionCount();
  }});

  document.addEventListener('change', function(e) {{
    if (e.target.classList.contains('candidate-checkbox')) {{
      updateSelectionCount();
    }}
  }});

  function updateSelectionCount() {{
    const checked = document.querySelectorAll('.candidate-checkbox:checked').length;
    const selBar   = document.getElementById('sel-bar');
    const batchBar = document.getElementById('batch-bar');
    if (checked > 0) {{
      selBar.style.display = 'block';
      selBar.textContent = checked + ' of ' + visibleRows.length + ' selected';
      batchBar.classList.add('visible');
    }} else {{
      selBar.style.display = 'none';
      batchBar.classList.remove('visible');
    }}
  }}

  // ── Grade multiple ─────────────────────────────────────────────────────────
  document.getElementById('btn-grade-selected').addEventListener('click', function() {{
    const entries = [...document.querySelectorAll('.candidate-checkbox:checked')]
      .map(cb => ({{code: cb.dataset.code, cid: cb.dataset.cid || ''}}));
    if (!entries.length) {{ alert('Select at least one candidate.'); return; }}
    gradeMultiple(entries);
  }});
  document.getElementById('btn-grade-all').addEventListener('click', function() {{
    const entries = [...document.querySelectorAll('.candidate-checkbox')]
      .map(cb => ({{code: cb.dataset.code, cid: cb.dataset.cid || ''}}));
    gradeMultiple(entries);
  }});
  document.querySelectorAll('.btn-grade:not(#batch-grade)').forEach(btn =>
    btn.addEventListener('click', () =>
      gradeMultiple([{{code: btn.dataset.code, cid: btn.dataset.cid || ''}}]))
  );
  document.getElementById('batch-grade')?.addEventListener('click', function() {{
    const entries = [...document.querySelectorAll('.candidate-checkbox:checked')]
      .map(cb => ({{code: cb.dataset.code, cid: cb.dataset.cid || ''}}));
    if (!entries.length) {{ alert('Select at least one candidate.'); return; }}
    gradeMultiple(entries);
  }});

  function gradeMultiple(entries) {{
    fetch('/grade', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{entries}})}})
      .then(r => r.json()).then(d => {{ alert(d.message); location.reload(); }})
      .catch(e => alert('Grade failed: ' + e));
  }}

  // ── Confirmation dialog helpers ────────────────────────────────────────────
  function showConfirm(title, msg) {{
    return new Promise(resolve => {{
      document.getElementById('confirm-title').textContent = title;
      document.getElementById('confirm-msg').textContent   = msg;
      const overlay = document.getElementById('confirm-overlay');
      overlay.style.display = 'flex';
      const okBtn = document.getElementById('confirm-ok');
      const cancelBtn = document.getElementById('confirm-cancel');
      function cleanup(val) {{
        overlay.style.display = 'none';
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        resolve(val);
      }}
      function onOk() {{ cleanup(true); }}
      function onCancel() {{ cleanup(false); }}
      okBtn.addEventListener('click', onOk);
      cancelBtn.addEventListener('click', onCancel);
    }});
  }}

  // ── Batch decision helper ──────────────────────────────────────────────────
  async function batchDecision(entries, decision, reason, label) {{
    if (!entries.length) {{ alert('No candidates selected.'); return; }}
    const confirmed = await showConfirm(
      label + ' ' + entries.length + ' candidate' + (entries.length !== 1 ? 's' : '') + '?',
      'This will record a "' + decision + '" decision for each selected candidate. This cannot be undone.'
    );
    if (!confirmed) return;

    const progressEl = document.getElementById('batch-progress');
    let done = 0;
    for (const entry of entries) {{
      progressEl.textContent = label + '... ' + done + '/' + entries.length + ' done';
      try {{
        await fetch('/record-decision', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{code: entry.code, cid: entry.cid, decision, reason, author: 'HM'}}),
        }});
      }} catch(e) {{
        console.error('Decision failed for', entry.code, e);
      }}
      done++;
    }}
    progressEl.textContent = 'Done! Reloading...';
    location.reload();
  }}

  document.getElementById('batch-advance')?.addEventListener('click', async function() {{
    const entries = [...document.querySelectorAll('.candidate-checkbox:checked')]
      .map(cb => ({{code: cb.dataset.code, cid: cb.dataset.cid || ''}}));
    await batchDecision(entries, 'next_round', 'Batch advance', 'Advance');
  }});

  document.getElementById('batch-reject')?.addEventListener('click', async function() {{
    const entries = [...document.querySelectorAll('.candidate-checkbox:checked')]
      .map(cb => ({{code: cb.dataset.code, cid: cb.dataset.cid || ''}}));
    await batchDecision(entries, 'reject', 'Batch reject', 'Reject');
  }});

  document.getElementById('batch-reject-below')?.addEventListener('click', async function() {{
    const threshold = parseFloat(document.getElementById('batch-threshold').value);
    if (isNaN(threshold)) {{ alert('Enter a score threshold first.'); return; }}
    // Only graded candidates in current view with score below threshold
    const entries = visibleRows
      .filter(r => r.dataset.score !== '' && parseFloat(r.dataset.score) < threshold)
      .map(r => ({{code: r.dataset.code, cid: r.dataset.cid || ''}}));
    if (!entries.length) {{
      alert('No graded candidates in the current view with score below ' + threshold + '.');
      return;
    }}
    await batchDecision(entries, 'reject', 'Batch reject (below ' + threshold + ')', 'Reject below ' + threshold);
  }});

  // ── Initial render ─────────────────────────────────────────────────────────
  applyFilterAndSort();
}})();
</script>
</body>
</html>"""


def _load_local_flags(code: str) -> list[dict]:
    """
    For local (non-relay) sessions: load flags.json if it exists, otherwise
    compute flags on the fly from events.jsonl + manifest.json.
    Returns an empty list on any error.
    """
    try:
        from interview.core.flags import compute_flags
        session_dir = SESSIONS_DIR / code
        flags_file = session_dir / "flags.json"
        if flags_file.exists():
            try:
                return json.loads(flags_file.read_text())
            except Exception:
                pass
        # Compute on the fly
        events_file = session_dir / "events.jsonl"
        manifest_file = session_dir / "manifest.json"
        if not events_file.exists():
            return []
        events: list[dict] = []
        for line in events_file.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
        manifest: dict = {}
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text())
            except Exception:
                pass
        return compute_flags(events, manifest)
    except Exception:
        return []


def _build_flags_panel_html(flags: list[dict]) -> str:
    """
    Build the HTML for the session flags panel.
    Returns an empty string when there are no flags.
    All flag text is HTML-escaped before rendering.
    """
    if not flags:
        return ""

    badges = ""
    for flag in flags:
        severity = flag.get("severity", "yellow")
        label    = escape(str(flag.get("label", "")))
        detail   = escape(str(flag.get("detail", "")))
        if severity == "red":
            bg     = "#fee2e2"
            border = "#ef4444"
            color  = "#991b1b"
        else:
            bg     = "#fef3c7"
            border = "#f59e0b"
            color  = "#92400e"
        badges += (
            f'<div style="background:{bg};border:1px solid {border};color:{color};'
            f'border-radius:6px;padding:10px 14px;margin-bottom:8px">'
            f'<div style="font-weight:600;font-size:13px;margin-bottom:2px">{label}</div>'
            f'<div style="font-size:12px">{detail}</div>'
            f'</div>'
        )

    return (
        f'<div class="panel" style="border-color:#2a2a2a">'
        f'<div class="section-title">Session Flags</div>'
        f'{badges}'
        f'</div>'
    )


# ─── Transcript renderer ─────────────────────────────────────────────────────

import re as _re


def _md_to_html(text: str) -> str:
    """Convert markdown subset → safe HTML. Escapes first, then substitutes."""
    fence_re = _re.compile(r"```[^\n]*\n(.*?)```", _re.DOTALL)
    parts = fence_re.split(text)
    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            result.append("<pre><code>" + escape(part) + "</code></pre>")
        else:
            s = escape(part)
            s = _re.sub(r"`([^`]+)`", lambda m: "<code>" + m.group(1) + "</code>", s)
            s = _re.sub(r"\*\*([^*]+)\*\*", lambda m: "<strong>" + m.group(1) + "</strong>", s)
            s = s.replace("\n", "<br>")
            result.append(s)
    return "".join(result)


def _is_session_banner(text: str) -> bool:
    """True if this assistant message is just re-displaying the session banner."""
    return "━━━" in text and "INTERVIEW SESSION" in text


def _tool_call_label(tool_name: str, tool_input: dict) -> str:
    """Return 'ToolName(args)' summary string for a tool call."""
    tn = escape(tool_name)
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        desc = tool_input.get("description", "")
        display = desc if desc else cmd
        if len(display) > 80:
            display = display[:77] + "..."
        return f"{tn}({escape(display)})"
    if tool_name in ("Read", "Edit", "Write"):
        fp = tool_input.get("file_path", "")
        return f"{tn}({escape(fp.split('/')[-1] or fp)})"
    if tool_name == "Grep":
        return f"{tn}({escape(tool_input.get('pattern', ''))})"
    if tool_name == "Glob":
        return f"{tn}({escape(tool_input.get('pattern', ''))})"
    first = next(iter(tool_input.values()), "") if tool_input else ""
    return f"{tn}({escape(str(first)[:60])})"


def _bash_output(response_summary: dict) -> str:
    """Extract clean stdout+stderr from a Bash tool result."""
    stdout = response_summary.get("stdout", "")
    stderr = response_summary.get("stderr", "")
    stdout = _re.sub(
        r"\[hash:[0-9a-f]+, (\d+) chars\]",
        lambda m: f"[output — {m.group(1)} chars, not captured]",
        stdout,
    )
    lines = [l for l in stdout.splitlines() if not l.startswith("[interview: ")]
    stdout = "\n".join(lines).strip()
    parts = []
    if stdout:
        parts.append(stdout)
    if stderr and stderr.strip():
        parts.append("stderr: " + stderr.strip())
    return "\n".join(parts) if parts else "(No output)"


def _diff_html(file_path: str, structured_patch: list, prefix: str = "⎿") -> str:
    """Render a structuredPatch list as a GitHub-style inline diff."""
    filename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    rows = []
    for hunk in structured_patch:
        old_s = hunk.get("oldStart", 0)
        old_l = hunk.get("oldLines", 0)
        new_s = hunk.get("newStart", 0)
        new_l = hunk.get("newLines", 0)
        rows.append(
            f'<div class="diff-hunk">@@ -{old_s},{old_l} +{new_s},{new_l} @@</div>'
        )
        for line in hunk.get("lines", []):
            if line.startswith("+"):
                rows.append(f'<div class="diff-add">+{escape(line[1:])}</div>')
            elif line.startswith("-"):
                rows.append(f'<div class="diff-del">-{escape(line[1:])}</div>')
            else:
                ctx = line[1:] if line.startswith(" ") else line
                rows.append(f'<div class="diff-ctx"> {escape(ctx)}</div>')
    return (
        f'<div class="diff-block">'
        f'<div class="diff-file">{escape(prefix)} {escape(filename)}</div>'
        + "".join(rows)
        + "</div>"
    )


def _render_tool_result(tool_name: str, response_summary: dict) -> str:
    """Return HTML for a tool result (⎿ block)."""
    if tool_name == "Bash":
        output = _bash_output(response_summary)
        return f'<div class="t-tool-result"><span class="t-arrow">⎿</span><span class="t-output">{escape(output)}</span></div>'
    if tool_name == "Read":
        fi = response_summary.get("file", {})
        content = fi.get("content", response_summary.get("text", "(No content)"))
        truncated = len(content) > 2000
        shown = escape(content[:2000]) + (" …" if truncated else "")
        return (
            f'<div class="t-tool-result"><span class="t-arrow">⎿</span>'
            f'<pre style="margin:4px 0;display:inline-block;vertical-align:top">'
            f'<code>{shown}</code></pre></div>'
        )
    if tool_name in ("Write", "Edit"):
        patch = response_summary.get("structuredPatch", [])
        fp = response_summary.get("filePath", "")
        if patch:
            return f'<div class="t-tool-result">{_diff_html(fp, patch)}</div>'
        # New file creation (no patch)
        content = response_summary.get("content", "")
        filename = fp.rsplit("/", 1)[-1] if "/" in fp else fp
        shown = escape(content[:2000]) + (" …" if len(content) > 2000 else "")
        return (
            f'<div class="t-tool-result">'
            f'<div class="diff-block">'
            f'<div class="diff-file">⎿ {escape(filename)} (new file)</div>'
            f'<pre style="margin:0;padding:8px"><code>{shown}</code></pre>'
            f'</div></div>'
        )
    # Generic
    return f'<div class="t-tool-result"><span class="t-arrow">⎿</span>{escape(str(response_summary)[:300])}</div>'


def _render_event_group(events: list) -> list:
    """Render a flat list of events (tool_call, tool_result, thinking) to HTML strings."""
    parts = []
    for ev in events:
        etype = ev.get("type", "")
        payload = ev.get("payload", {})
        if etype == "thinking":
            plan = escape(payload.get("plan", ""))
            elapsed = payload.get("_elapsed_minutes", 0)
            secs = round(elapsed * 60) if elapsed else 0
            parts.append(
                f'<details class="t-thinking">'
                f'<summary>✻ Cogitated {secs}s</summary>'
                f'<div style="padding:6px 0 0 12px;white-space:pre-wrap">{plan}</div>'
                f'</details>'
            )
        elif etype == "tool_call":
            label = _tool_call_label(payload.get("tool_name", ""), payload.get("tool_input", {}))
            parts.append(f'<div class="t-tool-call">⏺ {label}</div>')
        elif etype == "tool_result":
            parts.append(_render_tool_result(payload.get("tool_name", ""), payload.get("response_summary", {})))
    return parts


def _render_preamble(manifest: dict) -> str:
    """Synthesize the pre-session terminal interaction from manifest fields."""
    import datetime as _dt
    code        = manifest.get("code", "")
    started_at  = manifest.get("started_at", 0)
    cand_name   = manifest.get("candidate_name") or ""
    cand_email  = manifest.get("candidate_email") or ""
    github_user = manifest.get("github_username") or ""
    time_limit  = manifest.get("time_limit_minutes")
    problem     = manifest.get("problem") or ""

    parts = []
    parts.append(f'<div class="t-user">❯ /interview {escape(code)}</div>')

    # Name/email exchange — omit when GitHub OAuth handled identity
    if not github_user:
        if cand_name:
            parts.append('<div class="t-assistant"><span class="t-dot">⏺</span>What\'s your name?</div>')
            parts.append(f'<div class="t-user">❯ {escape(cand_name)}</div>')
        if cand_email:
            parts.append('<div class="t-assistant"><span class="t-dot">⏺</span>What\'s your email address?</div>')
            parts.append(f'<div class="t-user">❯ {escape(cand_email)}</div>')

    parts.append('<div class="t-assistant"><span class="t-dot">⏺</span>Starting your session now.</div>')

    # Format started_at timestamp
    if isinstance(started_at, (int, float)) and started_at:
        started_str = _dt.datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M")
    else:
        started_str = str(started_at)[:16].replace("T", " ")

    bar = "━" * 55
    banner_lines = [
        bar,
        f"  INTERVIEW SESSION \u2014 {code}",
        f"  Started: {started_str}",
    ]
    if github_user:
        banner_lines.append(f"  GitHub:  @{github_user}")
    if time_limit:
        banner_lines.append(f"  Time limit: {time_limit} minutes")
    banner_lines += [bar, "", "  PROBLEM STATEMENT", ""]
    for line in problem.split("\n"):
        banner_lines.append(f"  {line}")
    banner_lines += ["", bar, "  Session is recording. Type /submit when done.", bar]

    banner_text = "\n".join(banner_lines)
    parts.append(
        f'<div class="t-banner"><pre style="margin:0;white-space:pre-wrap;'
        f'color:#888;font-family:inherit">{escape(banner_text)}</pre></div>'
    )
    return "\n".join(parts)


def _render_transcript_html(events: list, manifest: dict | None = None) -> str:
    """Render events.jsonl list as a structured conversation transcript."""
    parts = ['<div class="transcript">']

    # ── Pre-session preamble (synthesized from manifest) ──────────────────────
    if manifest:
        parts.append(_render_preamble(manifest))

    # ── Partition events into preamble + conversation ─────────────────────────
    first_user_idx = next(
        (i for i, e in enumerate(events) if e.get("type") == "user_prompt"), None
    )
    preamble   = events[:first_user_idx] if first_user_idx is not None else events
    conv_events = events[first_user_idx:] if first_user_idx is not None else []

    # ── Preamble (setup) section ──────────────────────────────────────────────
    setup_items = [e for e in preamble if e.get("type") not in ("session_start",)]
    if setup_items:
        # Summary line: "Read, Write, Bash" etc.
        tool_names = []
        for e in setup_items:
            if e.get("type") == "tool_call":
                tn = e.get("payload", {}).get("tool_name", "")
                inp = e.get("payload", {}).get("tool_input", {})
                label = _tool_call_label(tn, inp)
                tool_names.append(label)
        summary = ", ".join(tool_names) if tool_names else f"{len(setup_items)} events"
        inner = "\n".join(_render_event_group(setup_items))
        parts.append(
            f'<details class="t-setup">'
            f'<summary>Session setup — {escape(summary)}</summary>'
            f'<div class="t-setup-body">{inner}</div>'
            f'</details>'
        )

    # ── Conversation turns ────────────────────────────────────────────────────
    # Events in events.jsonl are NOT in display order: PreToolUse/PostToolUse fire
    # during a turn, but the Stop hook logs user_prompt + assistant_message only at
    # the END of the turn. So tool_call/tool_result for Turn N appear in the log
    # BEFORE Turn N's user_prompt. We buffer them in `pending_tools` and attach
    # them to the next user_prompt we encounter.
    turns: list = []  # list of (user_event, tool_events, assistant_event_or_None)
    session_end_event = None
    current_user = None
    current_tools: list = []
    pending_tools: list = []  # tools seen after last assistant_message, before next user_prompt
    for ev in conv_events:
        t = ev.get("type", "")
        if t == "user_prompt":
            if current_user is not None:
                turns.append((current_user, current_tools, None))
            current_user = ev
            # Tools logged before this user_prompt belong to this turn
            current_tools = list(pending_tools)
            pending_tools = []
        elif t == "assistant_message":
            turns.append((current_user, list(current_tools), ev))
            current_user = None
            current_tools = []
            pending_tools = []
        elif t == "session_end":
            if current_user is not None:
                turns.append((current_user, current_tools, None))
                current_user = None
                current_tools = []
            pending_tools = []
            session_end_event = ev
        elif t in ("tool_call", "tool_result", "thinking"):
            if current_user is None:
                pending_tools.append(ev)  # buffer until next user_prompt
            else:
                current_tools.append(ev)
    # Flush any unclosed turn
    if current_user is not None:
        turns.append((current_user, current_tools, None))

    for user_ev, tool_evs, asst_ev in turns:
        if user_ev is None:
            continue
        # User prompt
        user_text = escape(user_ev.get("payload", {}).get("text", ""))
        parts.append(f'<div class="t-user">❯ {user_text}</div>')

        # Tool calls/results between user and assistant
        parts.extend(_render_event_group(tool_evs))

        # Assistant response — skip if it's just the session banner re-display
        if asst_ev is not None:
            text = asst_ev.get("payload", {}).get("text", "")
            if not _is_session_banner(text):
                parts.append(f'<div class="t-assistant"><span class="t-dot">⏺</span>{_md_to_html(text)}</div>')

    # ── Session end ───────────────────────────────────────────────────────────
    if session_end_event:
        payload = session_end_event.get("payload", {})
        elapsed = payload.get("elapsed_minutes", 0)
        diff_summary = escape(payload.get("git_diff_summary", ""))
        parts.append(
            f'<div class="t-end">'
            f'Submitted · {elapsed:.1f} min'
            + (f' · {diff_summary}' if diff_summary else '')
            + '</div>'
        )
        # Show full git diff from manifest (start → submit)
        git_diff = (manifest or {}).get("git_diff", "")
        if git_diff and git_diff.strip():
            diff_lines = []
            for line in git_diff.splitlines():
                if line.startswith("+++") or line.startswith("---"):
                    diff_lines.append(f'<div class="diff-file" style="background:#0a0a0a">{escape(line)}</div>')
                elif line.startswith("+"):
                    diff_lines.append(f'<div class="diff-add">+{escape(line[1:])}</div>')
                elif line.startswith("-"):
                    diff_lines.append(f'<div class="diff-del">-{escape(line[1:])}</div>')
                elif line.startswith("@@"):
                    diff_lines.append(f'<div class="diff-hunk">{escape(line)}</div>')
                else:
                    diff_lines.append(f'<div class="diff-ctx"> {escape(line)}</div>')
            parts.append(
                f'<details class="t-gitdiff" open>'
                f'<summary>Full diff (start → submit) · {escape(diff_summary)}</summary>'
                f'<div class="diff-block" style="margin-top:6px">{"".join(diff_lines)}</div>'
                f'</details>'
            )

    if len(parts) <= (2 if manifest else 1):
        parts.append('<div style="color:#555;font-size:13px">No session events recorded.</div>')

    parts.append('</div>')
    return "\n".join(parts)


def _build_candidate_detail_html(code: str, cid: str = "") -> str:
    """Full candidate detail page: report + comments + decision buttons."""
    from interview.core.decisions import get_comments, get_decision, is_graded
    from interview.core.audit import read_events as read_audit_events

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
        current_grading = relay_session.get("grading") or {}
        grading_history = relay_session.get("grading_history", [])
        session_flags   = relay_session.get("flags", [])
    else:
        raw_comments    = get_comments(code)
        decision_obj    = get_decision(code)
        graded          = is_graded(code)
        audit_events    = read_audit_events(code)
        current_grading = {}
        grading_history = []
        # Load or compute flags for local sessions
        session_flags = _load_local_flags(code)

    # Load events + manifest for transcript view
    if relay_session:
        _events = relay_session.get("events", [])
        _manifest_dict = relay_session.get("manifest", {}) or {}
    else:
        _events_file = SESSIONS_DIR / code / "events.jsonl"
        _events = []
        if _events_file.exists():
            for _line in _events_file.read_text().splitlines():
                try:
                    _events.append(json.loads(_line))
                except Exception:
                    pass
        _mf_path = SESSIONS_DIR / code / "manifest.json"
        _manifest_dict = {}
        if _mf_path.exists():
            try:
                _manifest_dict = json.loads(_mf_path.read_text())
            except Exception:
                pass
    transcript_html = _render_transcript_html(_events, manifest=_manifest_dict)

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


    # Grade panel (relay mode — when we have grading data)
    grade_panel_html = ""
    if graded and current_grading:
        current_score   = current_grading.get("overall_score")
        current_summary = escape(current_grading.get("summary", ""))
        score_display   = f"{current_score} / 10" if current_score is not None else "—"
        graded_by_val   = current_grading.get("graded_by", "hm")

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

        # Build graded-by label for the detail page
        if graded_by_val == "auto":
            graded_by_label = (
                '<span title="Graded automatically on submission" '
                'style="font-size:11px;color:#60a5fa;background:#0c1a2e;'
                'border:1px solid #1e40af;border-radius:10px;padding:2px 8px;'
                'margin-left:8px;vertical-align:middle">Auto-graded</span>'
            )
        else:
            graded_by_label = (
                '<span title="Graded by hiring manager" '
                'style="font-size:11px;color:#a3a3a3;background:#1a1a1a;'
                'border:1px solid #333;border-radius:10px;padding:2px 8px;'
                'margin-left:8px;vertical-align:middle">HM-graded</span>'
            )

        revise_score_val = current_score if current_score is not None else ""
        grade_panel_html = f"""
    <div class="panel" id="grade-panel">
      <div class="section-title">Grade</div>
      <div style="font-size:22px;font-weight:700;color:#fbbf24;margin-bottom:4px">
        {score_display}{revision_badge}{graded_by_label}
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

    # Flags panel
    flags_panel_html = _build_flags_panel_html(session_flags)

    # Analysis panel — Claude's rubric-based grading analysis (HM-only, left column)
    analysis_panel_html = ""
    if graded and current_grading:
        an_summary    = escape(current_grading.get("summary", ""))
        an_dimensions = current_grading.get("dimensions", [])
        an_standouts  = current_grading.get("standout_moments", [])
        an_concerns   = current_grading.get("concerns", [])

        # Dimension rows
        dim_rows = ""
        for dim in an_dimensions:
            d_name  = escape(str(dim.get("name", "")))
            d_score = dim.get("score")
            d_just  = escape(str(dim.get("justification", "")))
            score_pct = int((d_score / 10) * 100) if d_score is not None else 0
            score_color = (
                "#4ade80" if score_pct >= 70 else
                "#fbbf24" if score_pct >= 40 else
                "#f87171"
            )
            score_label = f"{d_score}/10" if d_score is not None else "—"
            dim_rows += (
                f'<div style="margin-bottom:12px">'
                f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px">'
                f'<span style="font-size:12px;color:#ccc">{d_name}</span>'
                f'<span style="font-size:12px;font-weight:600;color:{score_color}">{score_label}</span>'
                f'</div>'
                f'<div style="height:3px;background:#1a1a1a;border-radius:2px;margin-bottom:5px">'
                f'<div style="height:3px;width:{score_pct}%;background:{score_color};border-radius:2px"></div>'
                f'</div>'
                f'<div style="font-size:11px;color:#555;line-height:1.5">{d_just}</div>'
                f'</div>'
            )

        # Standout moments
        standout_html = ""
        if an_standouts:
            items = "".join(
                f'<li style="margin-bottom:4px">{escape(str(s))}</li>'
                for s in an_standouts
            )
            standout_html = (
                f'<div style="margin-top:14px">'
                f'<div style="font-size:10px;color:#4ade80;text-transform:uppercase;'
                f'letter-spacing:0.08em;margin-bottom:6px">Standout moments</div>'
                f'<ul style="margin:0;padding-left:16px;font-size:12px;color:#888;line-height:1.6">'
                f'{items}</ul></div>'
            )

        # Concerns
        concerns_html = ""
        if an_concerns:
            items = "".join(
                f'<li style="margin-bottom:4px">{escape(str(c))}</li>'
                for c in an_concerns
            )
            concerns_html = (
                f'<div style="margin-top:14px">'
                f'<div style="font-size:10px;color:#f87171;text-transform:uppercase;'
                f'letter-spacing:0.08em;margin-bottom:6px">Concerns</div>'
                f'<ul style="margin:0;padding-left:16px;font-size:12px;color:#888;line-height:1.6">'
                f'{items}</ul></div>'
            )

        analysis_panel_html = (
            f'<div class="panel" id="analysis-panel">'
            f'<div class="section-title">Claude\'s Analysis '
            f'<span style="color:#555;font-size:10px;font-weight:400">· HM-only · rubric-based</span></div>'
            + (f'<div style="font-size:13px;color:#b0b0b0;margin-bottom:16px;line-height:1.6">{an_summary}</div>'
               if an_summary else '')
            + dim_rows
            + standout_html
            + concerns_html
            + '</div>'
        )

    safe_code = escape(code)
    safe_cid = escape(cid) if cid else ""
    # Use JSON encoding for JS string literals to prevent JS injection
    js_code = json.dumps(code)
    js_cid  = json.dumps(cid)
    cid_attr = f'data-cid="{safe_cid}"' if cid else ""

    # Identity fields — always shown
    cand_email    = relay_session.get("candidate_email", "") if relay_session else ""
    cand_name     = relay_session.get("candidate_name", "")  if relay_session else ""
    cand_username = relay_session.get("github_username", "")  if relay_session else ""
    cand_repo_url = relay_session.get("github_repo_url", "")  if relay_session else ""
    cand_avatar   = relay_session.get("avatar_url", "")       if relay_session else ""

    # Pre-build HTML fragments (no backslashes in f-string expressions — Python 3.10+)
    onerror_attr = "onerror=\"this.style.display='none'\""
    avatar_html = (
        '<img src="' + escape(cand_avatar) + '" style="width:48px;height:48px;'
        'border-radius:50%;flex-shrink:0" ' + onerror_attr + '>'
        if cand_avatar else ''
    )
    name_html = (
        '<div style="font-size:14px;font-weight:600;color:#e0e0e0;margin-bottom:2px">'
        + escape(cand_name) + '</div>'
        if cand_name else ''
    )
    email_html = (
        '<div style="font-size:13px;color:#888;margin-bottom:4px">'
        + escape(cand_email) + '</div>'
        if cand_email else ''
    )
    gh_user_html = (
        '<div style="font-size:12px;margin-bottom:4px"><a href="https://github.com/'
        + escape(cand_username) + '" target="_blank" style="color:#60a5fa;text-decoration:none">@'
        + escape(cand_username) + '</a></div>'
        if cand_username else ''
    )
    repo_html = (
        '<div style="font-size:12px"><a href="' + escape(cand_repo_url)
        + '" target="_blank" style="color:#4ade80;text-decoration:none">View code repository →</a></div>'
        if cand_repo_url else ''
    )
    no_identity_note = (
        '<div style="font-size:13px;color:#555">No identity info — GitHub OAuth not configured.</div>'
        if not any([cand_name, cand_email, cand_username]) else ''
    )
    identity_block = f"""
      <div style="display:flex;align-items:flex-start;gap:14px">
        {avatar_html}
        <div style="min-width:0">
          {name_html}
          {email_html}
          {gh_user_html}
          {repo_html}
          {no_identity_note}
        </div>
      </div>"""
    identity_panel = f'<div class="panel"><div class="section-title">Identity</div>{identity_block}</div>'

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
  .back-link {{ color: #60a5fa; text-decoration: none; font-size: 13px; margin-bottom: 24px; display: block; }}
  .reason-input {{ width: 100%; margin-top: 8px; background: #0a0a0a; border: 1px solid #333;
                   color: #e0e0e0; border-radius: 6px; padding: 8px; font-size: 13px; }}
  .transcript {{ font-family: 'Menlo','Consolas','Monaco',monospace; font-size: 13px;
                 line-height: 1.7; background: #0a0a0a; color: #d4d4d4; padding: 20px;
                 border-radius: 6px; overflow-x: auto; max-height: 75vh; overflow-y: auto; }}
  .t-banner {{ margin-bottom: 6px; }}
  .t-debrief {{ border-top: 1px solid #1a1a1a; margin-top: 16px; padding-top: 14px; }}
  .t-debrief-body {{ color: #b0b0b0; font-size: 13px; line-height: 1.7; padding-left: 4px; }}
  .t-setup {{ color: #444; font-size: 12px; margin: 8px 0; border-left: 2px solid #222;
              padding-left: 10px; }}
  .t-setup summary {{ cursor: pointer; list-style: none; }}
  .t-setup summary::-webkit-details-marker {{ display: none; }}
  .t-setup-body {{ padding-top: 6px; }}
  .t-user {{ color: #f97316; white-space: pre-wrap; margin: 14px 0 6px 0;
             font-weight: 600; }}
  .t-assistant {{ color: #e0e0e0; margin: 6px 0 14px 0; padding-left: 18px;
                  border-left: 2px solid #2a2a5a; }}
  .t-dot {{ color: #60a5fa; margin-right: 6px; }}
  .t-tool-call {{ color: #a78bfa; margin: 8px 0 2px 0; }}
  .t-tool-result {{ color: #6b7280; margin: 0 0 8px 0; padding-left: 16px; }}
  .t-arrow {{ margin-right: 4px; }}
  .t-output {{ white-space: pre-wrap; }}
  .t-thinking {{ color: #444; margin: 4px 0; font-size: 12px; }}
  .t-thinking summary {{ list-style: none; cursor: pointer; }}
  .t-thinking summary::-webkit-details-marker {{ display: none; }}
  .t-end {{ color: #555; border-top: 1px solid #1a1a1a; margin-top: 16px;
             padding-top: 12px; font-size: 12px; }}
  .t-gitdiff {{ color: #444; font-size: 12px; margin-top: 8px; }}
  .t-gitdiff summary {{ cursor: pointer; list-style: none; color: #555; }}
  .t-gitdiff summary::-webkit-details-marker {{ display: none; }}
  .transcript code {{ background: #1a1a1a; padding: 1px 4px; border-radius: 3px; font-size: 12px; }}
  .transcript pre {{ background: #111; border: 1px solid #1e1e1e; border-radius: 4px;
                     padding: 10px; overflow-x: auto; margin: 4px 0; white-space: pre; }}
  .transcript pre code {{ background: none; padding: 0; }}
  .diff-block {{ border: 1px solid #222; border-radius: 4px; overflow: hidden;
                 font-family: 'Menlo','Consolas','Monaco',monospace; font-size: 12px;
                 margin: 4px 0; display: block; }}
  .diff-file {{ background: #111; color: #888; padding: 4px 10px;
                border-bottom: 1px solid #222; font-size: 11px; }}
  .diff-hunk {{ background: #0c1a2e; color: #4a6fa5; padding: 2px 10px; font-size: 11px; }}
  .diff-add {{ background: #0a1f0a; color: #4ade80; padding: 1px 10px; white-space: pre; }}
  .diff-del {{ background: #1f0a0a; color: #f87171; padding: 1px 10px; white-space: pre; }}
  .diff-ctx {{ background: #0a0a0a; color: #555; padding: 1px 10px; white-space: pre; }}
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
    {identity_panel}
    {flags_panel_html}
    <div class="panel">
      <div class="section-title">Transcript</div>
      {transcript_html}
    </div>
    {analysis_panel_html}
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
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, data: dict, status=200):
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(encoded))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        from interview.core import audit as audit_mod
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/" or path == "/dashboard":
            reports = _load_all_reports()
            filter_code = params.get("filter", [""])[0]
            if filter_code:
                reports = [r for r in reports if r.get("code") == filter_code]
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


def start_dashboard(code: str | None = None):
    ensure_dirs()
    base_url = f"http://localhost:{PORT}"
    open_url = f"{base_url}/?filter={code}" if code else base_url
    relay = get_relay_url()
    print(f"\n✓ interviewsignal dashboard running at {base_url}")
    if relay:
        print(f"  Relay:  {relay}")
        print(f"  Mode:   relay — submissions fetched from relay automatically")
    else:
        print(f"  Mode:   email — save report JSON attachments to ~/.interview/received/")
        print(f"  Tip:    run 'interview configure-relay' to connect a relay server")
    print(f"  Press Ctrl+C to stop.\n")
    webbrowser.open(open_url)

    server = http.server.HTTPServer(("localhost", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")


if __name__ == "__main__":
    import sys as _sys
    start_dashboard(_sys.argv[1] if len(_sys.argv) > 1 else None)

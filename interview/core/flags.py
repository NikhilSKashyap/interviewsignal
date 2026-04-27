"""
interview.core.flags
--------------------
Compute session quality flags from existing event data.
Pure functions — no side effects, no network calls, stdlib only.

Two categories of flags:
  1. Session quality  — too_fast, few_interactions, no_iteration, uniform_timing, no_prompts
  2. Tamper detection — hooks_gap, diff_event_mismatch, heartbeat_gap, prompt_event_ratio
"""

import statistics


def compute_flags(events: list[dict], manifest: dict) -> list[dict]:
    """
    Analyse a list of session events and the session manifest, returning a list
    of quality-flag dicts:
        [{"id": "...", "severity": "yellow"|"red", "label": "...", "detail": "..."}]

    Each flag is computed independently.  If a flag cannot be computed (missing
    data, etc.) it is silently skipped.  The function itself never raises.
    """
    flags: list[dict] = []

    # Session quality flags
    try:
        flags.extend(_flag_too_fast(manifest))
    except Exception:
        pass

    try:
        flags.extend(_flag_few_interactions(events))
    except Exception:
        pass

    try:
        flags.extend(_flag_no_iteration(events))
    except Exception:
        pass

    try:
        flags.extend(_flag_uniform_timing(events))
    except Exception:
        pass

    try:
        flags.extend(_flag_no_prompts(events))
    except Exception:
        pass

    # Tamper detection flags
    try:
        flags.extend(_flag_hooks_gap(events, manifest))
    except Exception:
        pass

    try:
        flags.extend(_flag_diff_event_mismatch(events, manifest))
    except Exception:
        pass

    try:
        flags.extend(_flag_prompt_event_ratio(events, manifest))
    except Exception:
        pass

    try:
        flags.extend(_flag_commit_event_mismatch(events, manifest))
    except Exception:
        pass

    return flags


# ── individual flag detectors ─────────────────────────────────────────────────

def _flag_too_fast(manifest: dict) -> list[dict]:
    """Proportional thresholds against time_limit; absolute fallback when no limit set."""
    elapsed = manifest.get("elapsed_minutes")
    if elapsed is None:
        return []

    elapsed = float(elapsed)
    time_limit = manifest.get("time_limit_minutes")

    if time_limit:
        time_limit = float(time_limit)
        if time_limit <= 0:
            return []
        pct = elapsed / time_limit * 100
        if pct < 10:
            return [{
                "id":       "too_fast",
                "severity": "red",
                "label":    "Completed very quickly",
                "detail":   (
                    f"Session lasted {elapsed:.1f} min — "
                    f"{pct:.0f}% of the {time_limit:.0f}-minute limit."
                ),
            }]
        if pct < 20:
            return [{
                "id":       "too_fast",
                "severity": "yellow",
                "label":    "Completed unusually quickly",
                "detail":   (
                    f"Session lasted {elapsed:.1f} min — "
                    f"{pct:.0f}% of the {time_limit:.0f}-minute limit."
                ),
            }]
        return []

    # No time limit — flag only if genuinely very short (< 5 min)
    if elapsed < 5:
        return [{
            "id":       "too_fast",
            "severity": "yellow",
            "label":    "Very short session",
            "detail":   f"Session lasted {elapsed:.1f} min with no time limit set.",
        }]

    return []


_INTERACTION_TYPES = {"tool_call", "file_read", "file_write", "file_edit", "bash_command"}


def _flag_few_interactions(events: list[dict]) -> list[dict]:
    """Yellow if 3–4 interactions; Red if < 3."""
    count = sum(1 for e in events if e.get("type") in _INTERACTION_TYPES)

    if count < 3:
        return [{
            "id":       "few_interactions",
            "severity": "red",
            "label":    "Very few tool interactions",
            "detail":   f"Only {count} tool interaction(s) recorded.",
        }]
    if count <= 4:
        return [{
            "id":       "few_interactions",
            "severity": "yellow",
            "label":    "Few tool interactions",
            "detail":   f"Only {count} tool interaction(s) recorded.",
        }]
    return []


def _flag_no_iteration(events: list[dict]) -> list[dict]:
    """
    Yellow when there are >3 tool calls but no sign of iteration:
      - bash_command with nonzero exit followed within 5 events by a file_edit/file_write, OR
      - file_write followed later by a file_edit to the same path.
    """
    tool_count = sum(1 for e in events if e.get("type") in _INTERACTION_TYPES)
    if tool_count <= 3:
        return []  # not enough events to judge

    iteration_found = False

    for i, event in enumerate(events):
        etype = event.get("type", "")

        # Pattern 1: failed bash then edit/write within 5 events
        if etype == "bash_command":
            exit_code = event.get("exit_code")
            try:
                exit_code_int = int(exit_code) if exit_code is not None else 0
            except (TypeError, ValueError):
                exit_code_int = 0
            if exit_code_int != 0:
                window = events[i + 1 : i + 6]
                for follow in window:
                    if follow.get("type") in ("file_edit", "file_write"):
                        iteration_found = True
                        break

        # Pattern 2: file_write then file_edit to the same path
        if etype == "file_write":
            written_path = event.get("path") or event.get("file")
            if written_path:
                for follow in events[i + 1 :]:
                    if follow.get("type") == "file_edit":
                        if (follow.get("path") or follow.get("file")) == written_path:
                            iteration_found = True
                            break

        if iteration_found:
            break

    if not iteration_found:
        return [{
            "id":       "no_iteration",
            "severity": "yellow",
            "label":    "No iteration detected",
            "detail":   "No evidence of fixing errors or refining code after an initial write.",
        }]
    return []


_TIMING_TYPES = {"user_prompt", "tool_call", "thinking"}


def _flag_uniform_timing(events: list[dict]) -> list[dict]:
    """
    Red if coefficient of variation (stdev/mean) < 0.15;
    Yellow if < 0.30.
    Requires at least 5 inter-event gaps.
    """
    timestamps = [
        e["timestamp_ms"]
        for e in events
        if e.get("type") in _TIMING_TYPES and e.get("timestamp_ms") is not None
    ]

    if len(timestamps) < 6:  # need at least 6 points for 5 gaps
        return []

    gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]

    if len(gaps) < 5:
        return []

    mean = sum(gaps) / len(gaps)
    if mean == 0:
        return []

    stdev = statistics.stdev(gaps)
    cv = stdev / mean

    if cv < 0.15:
        return [{
            "id":       "uniform_timing",
            "severity": "red",
            "label":    "Suspiciously uniform timing",
            "detail":   (
                f"Inter-event timing is nearly constant (CV={cv:.2f}). "
                "This may indicate automated or scripted input."
            ),
        }]
    if cv < 0.30:
        return [{
            "id":       "uniform_timing",
            "severity": "yellow",
            "label":    "Unusually uniform timing",
            "detail":   f"Inter-event timing shows low variation (CV={cv:.2f}).",
        }]
    return []


def _flag_no_prompts(events: list[dict]) -> list[dict]:
    """Yellow when no user_prompt or thinking events are present."""
    count = sum(1 for e in events if e.get("type") in ("user_prompt", "thinking"))
    if count == 0:
        return [{
            "id":       "no_prompts",
            "severity": "yellow",
            "label":    "No prompts or thinking recorded",
            "detail":   "No user_prompt or thinking events found in the session log.",
        }]
    return []


# ── tamper detection flags ───────────────────────────────────────────────────

def _flag_hooks_gap(events: list[dict], manifest: dict) -> list[dict]:
    """
    Detect long gaps in the event stream that suggest hooks were disabled
    mid-session. If the session ran for N minutes but has a gap > 33% of
    total elapsed time with no events, flag it.

    Red   if largest gap > 50% of elapsed time.
    Yellow if largest gap > 33% of elapsed time.
    """
    elapsed = manifest.get("elapsed_minutes")
    if not elapsed or float(elapsed) < 5:
        return []  # too short to judge

    elapsed_ms = float(elapsed) * 60 * 1000

    timestamps = []
    for e in events:
        ts = e.get("timestamp_ms") or e.get("timestamp")
        if ts is not None:
            # Normalise: if timestamp is in seconds (< 1e12), convert to ms
            ts = float(ts)
            if ts < 1e12:
                ts = ts * 1000
            timestamps.append(ts)

    if len(timestamps) < 3:
        return []  # not enough events to compute gaps

    timestamps.sort()
    gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    max_gap = max(gaps)

    gap_pct = max_gap / elapsed_ms if elapsed_ms > 0 else 0
    gap_minutes = max_gap / 60000

    if gap_pct > 0.50:
        return [{
            "id":       "hooks_gap",
            "severity": "red",
            "label":    "Large gap in event stream",
            "detail":   (
                f"Longest gap between events: {gap_minutes:.1f} min "
                f"({gap_pct:.0%} of {float(elapsed):.0f}-min session). "
                "Hooks may have been disabled mid-session."
            ),
        }]
    if gap_pct > 0.33:
        return [{
            "id":       "hooks_gap",
            "severity": "yellow",
            "label":    "Notable gap in event stream",
            "detail":   (
                f"Longest gap between events: {gap_minutes:.1f} min "
                f"({gap_pct:.0%} of {float(elapsed):.0f}-min session)."
            ),
        }]
    return []


def _flag_diff_event_mismatch(events: list[dict], manifest: dict) -> list[dict]:
    """
    Cross-check git diff size against recorded Write/Edit tool calls.
    If the diff shows significant code changes but the event log has very few
    file-modifying tool calls, the candidate likely worked outside the AI
    assistant or disabled hooks during coding.

    Uses git_diff_summary from manifest ("N lines changed") and counts
    tool_call events with tool_name containing Write or Edit.

    Red   if diff >= 100 lines but < 3 write/edit tool calls.
    Yellow if diff >= 50 lines but < 3 write/edit tool calls.
    """
    diff_summary = manifest.get("git_diff_summary", "")
    diff_note = manifest.get("git_diff_note", "")

    # Skip if no diff data or no changes
    if not diff_summary or diff_note in ("no-git-repo", "no-changes"):
        return []

    # Parse "N lines changed" from summary
    diff_lines = 0
    try:
        parts = diff_summary.split()
        if parts and parts[0].isdigit():
            diff_lines = int(parts[0])
    except (ValueError, IndexError):
        return []

    if diff_lines < 50:
        return []

    # Count Write and Edit tool calls in events
    write_edit_count = 0
    for e in events:
        if e.get("type") != "tool_call":
            continue
        payload = e.get("payload", {})
        tool_name = payload.get("tool_name", "") if isinstance(payload, dict) else ""
        if not tool_name:
            tool_name = e.get("tool_name", "")
        tool_lower = tool_name.lower()
        if "write" in tool_lower or "edit" in tool_lower:
            write_edit_count += 1

    if write_edit_count >= 3:
        return []

    if diff_lines >= 100:
        return [{
            "id":       "diff_event_mismatch",
            "severity": "red",
            "label":    "Code changes don't match event log",
            "detail":   (
                f"Git diff shows {diff_lines} lines changed but only "
                f"{write_edit_count} Write/Edit tool call(s) recorded. "
                "Candidate may have worked outside the AI assistant or "
                "hooks were disabled during coding."
            ),
        }]
    return [{
        "id":       "diff_event_mismatch",
        "severity": "yellow",
        "label":    "Code changes may not match event log",
        "detail":   (
            f"Git diff shows {diff_lines} lines changed but only "
            f"{write_edit_count} Write/Edit tool call(s) recorded."
        ),
    }]


def _flag_prompt_event_ratio(events: list[dict], manifest: dict) -> list[dict]:
    """
    Check ratio of user prompts to tool calls. In a normal AI-assisted session,
    user prompts drive tool calls — roughly 1 prompt per 2-8 tool calls.
    If there are many tool calls but zero or very few prompts, the prompt
    capture may have been tampered with or hooks partially disabled.

    Yellow if tool_calls >= 10 and prompts == 0.
    Yellow if tool_calls >= 20 and prompt ratio < 1:20.
    """
    tool_calls = sum(1 for e in events if e.get("type") == "tool_call")
    prompts = sum(1 for e in events if e.get("type") == "user_prompt")

    if tool_calls < 10:
        return []

    if prompts == 0:
        return [{
            "id":       "prompt_event_ratio",
            "severity": "yellow",
            "label":    "Tool calls with no prompts",
            "detail":   (
                f"{tool_calls} tool calls recorded but zero user prompts. "
                "Prompt capture may have been disabled."
            ),
        }]

    if tool_calls >= 20 and prompts * 20 < tool_calls:
        ratio = tool_calls // prompts if prompts > 0 else tool_calls
        return [{
            "id":       "prompt_event_ratio",
            "severity": "yellow",
            "label":    "Unusually low prompt-to-tool ratio",
            "detail":   (
                f"{tool_calls} tool calls but only {prompts} prompt(s) "
                f"(ratio 1:{ratio}). Some prompts may not have been captured."
            ),
        }]

    return []


def _flag_commit_event_mismatch(events: list[dict], manifest: dict) -> list[dict]:
    """
    Cross-check the per-prompt commit log against Write/Edit tool calls.

    Direction 1 — session commits exist but zero Write/Edit tool calls:
      Code was committed but no file writes were recorded through the AI
      assistant. Candidate likely wrote code directly outside the AI tool.

    Direction 2 — Write/Edit tool calls exist but no session commits:
      AI was used to write files but no per-prompt commits were created.
      Suggests the Stop hook was disabled after session start.
    """
    commit_log = manifest.get("commit_log", [])

    # Filter out the initial "session start" commit
    session_commits = [
        c for c in commit_log
        if "session start" not in c.get("message", "")
    ]

    # Count Write/Edit tool calls
    write_edit_count = 0
    for e in events:
        if e.get("type") != "tool_call":
            continue
        payload = e.get("payload", {})
        tool_name = payload.get("tool_name", "") if isinstance(payload, dict) else ""
        if not tool_name:
            tool_name = e.get("tool_name", "")
        tl = tool_name.lower()
        if "write" in tl or "edit" in tl:
            write_edit_count += 1

    # Direction 1: commits with no AI file writes → worked outside AI assistant
    if session_commits and write_edit_count == 0:
        return [{
            "id":       "commit_event_mismatch",
            "severity": "red",
            "label":    "Code committed outside AI assistant",
            "detail":   (
                f"{len(session_commits)} commit(s) recorded but zero Write/Edit "
                "tool calls in the session log. Candidate likely wrote code "
                "directly outside the AI assistant."
            ),
        }]

    # Direction 2: AI file writes with no per-prompt commits → hook commits missing
    if write_edit_count >= 3 and not session_commits:
        return [{
            "id":       "commit_event_mismatch",
            "severity": "yellow",
            "label":    "Per-prompt commits missing",
            "detail":   (
                f"{write_edit_count} Write/Edit tool call(s) recorded but no "
                "per-prompt commits found in session. Stop hook may have been "
                "disabled after session start."
            ),
        }]

    return []

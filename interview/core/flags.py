"""
interview.core.flags
--------------------
Compute session quality flags from existing event data.
Pure functions — no side effects, no network calls, stdlib only.
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

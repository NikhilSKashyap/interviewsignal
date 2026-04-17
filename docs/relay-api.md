# Relay API Contract

The relay is an optional self-hosted HTTP server that replaces email as the transport layer
between candidates and hiring managers. When `relay_url` is set in config, all submissions
route through it. Without it, the system falls back to email — fully backward compatible.

The relay is deliberately dumb: it stores sealed session packages and serves them back.
It does not grade. It does not send email. It does not decrypt anything.

---

## Authentication

Every request requires:

```
Authorization: Bearer <api_key>
```

The API key is set at relay deployment time via the `RELAY_API_KEY` environment variable.
Both candidates and HMs use the same key — the relay is an internal service, behind your
VPN or private network. OAuth/SSO is Phase 2.

Requests without a valid key return `401 Unauthorized`.

---

## Endpoints

### `POST /sessions`
**Who:** Candidate (on `/submit`)
**What:** Submit a sealed session package.

Request body (JSON):
```json
{
  "code": "INT-4829-XK",
  "candidate_email": "jane@example.com",
  "candidate_name": "Jane Doe",
  "github_username": "janedoe",
  "github_repo_url": "https://github.com/janedoe/interview-INT-4829-XK",
  "manifest_json":  "<base64-encoded manifest.json>",
  "events_jsonl":   "<base64-encoded events.jsonl>",
  "report_html":    "<base64-encoded report.html>",
  "report_json":    "<base64-encoded report.json>"
}
```

- `manifest_json` and `events_jsonl` are required. The relay rejects submissions without them.
- `report_html` and `report_json` are optional — if absent, the HM can still grade and a report
  can be regenerated from the raw session data.
- `candidate_name`, `github_username`, and `github_repo_url` are optional. They are populated
  when GitHub OAuth is used and repo creation succeeds.
- `github_repo_url` is `null` if git push failed or OAuth is not configured.
- If a session with this code already exists, returns `409 Conflict`. Submissions are immutable.

Response `201 Created`:
```json
{ "code": "INT-4829-XK", "submitted_at": "2026-04-13T10:32:00Z" }
```

---

### `GET /sessions`
**Who:** HM dashboard
**What:** List all sessions submitted to this relay.

Response `200 OK`:
```json
[
  {
    "code": "INT-4829-XK",
    "submitted_at": "2026-04-13T10:32:00Z",
    "elapsed_minutes": 47,
    "overall_score": null,
    "graded": false,
    "revealed": false
  }
]
```

Ordered by `submitted_at` descending (most recent first).

---

### `GET /sessions/{code}`
**Who:** HM dashboard
**What:** Full session detail — everything needed to render the candidate page.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "submitted_at": "2026-04-13T10:32:00Z",
  "revealed": false,
  "candidate_email": null,
  "candidate_name": null,
  "github_username": null,
  "github_repo_url": null,
  "avatar_url": null,
  "manifest": { "elapsed_minutes": 47, "event_count": 38, ... },
  "report": { "overall_score": null, "dimensions": [], ... },
  "grading": null,
  "comments": [],
  "decision": null,
  "audit_entries": []
}
```

`candidate_email`, `candidate_name`, `github_username`, `github_repo_url`, and `avatar_url`
are only populated when `revealed: true` — until then they are `null` to enforce blind grading.

`report_html` is not included here — fetch separately to avoid large payloads in the list view.

---

### `GET /sessions/{code}/report.html`
**Who:** HM dashboard (iframe embed)
**What:** The raw HTML report file. Returns `text/html`.

---

### `GET /sessions/{code}/events`
**Who:** HM dashboard (grader)
**What:** Raw `events.jsonl` content. Returns `text/plain`, one JSON object per line.

This is what the grader reads to rebuild the session transcript. The relay serves it verbatim —
no transformation.

---

### `POST /sessions/{code}/grade`
**Who:** HM dashboard (after clicking "Grade" or "Submit Revision")
**What:** Save or revise a grading result. The dashboard runs grading locally using the
HM's API key and posts the result here for persistence and audit logging.

**First grade** — request body (JSON):
```json
{
  "dimensions": [
    { "name": "Problem Decomposition", "score": 8, "justification": "..." }
  ],
  "overall_score": 7.7,
  "summary": "...",
  "standout_moments": ["..."],
  "concerns": ["..."]
}
```

Response `200 OK`:
```json
{ "code": "INT-4829-XK", "cid": "abc123def456", "graded_at": "2026-04-13T10:47:22Z" }
```

**Grade revision** — include a `reason` field in the request body:
```json
{
  "dimensions": [...],
  "overall_score": 8.2,
  "summary": "...",
  "reason": "Undervalued the store abstraction — the session showed clearer separation of concerns than initially assessed."
}
```

If the session is already graded and `reason` is missing or empty, returns `400`:
```json
{ "error": "revision_requires_reason", "message": "Grade revision requires a 'reason' field explaining the change." }
```

Response `200 OK` for a revision:
```json
{
  "code": "INT-4829-XK",
  "cid": "abc123def456",
  "graded_at": "2026-04-13T11:30:00Z",
  "revision": true,
  "previous_score": 7.7,
  "new_score": 8.2
}
```

The previous grade is moved to `grading_history.jsonl` before overwriting `grading.json`.
The audit trail records a `grade_revised` event:
```json
{
  "type": "grade_revised",
  "code": "INT-4829-XK",
  "previous_score": 7.7,
  "new_score": 8.2,
  "reason": "Undervalued the store abstraction...",
  "revealed": true,
  "ts": "2026-04-13T11:30:00Z",
  "prev_hash": "d4abe5e6",
  "hash": "9f2c1a3b"
}
```

The `revealed` field records whether the candidate's identity was known at the time of
revision — the key data point for proving merit-first evaluation.

`grading_history.jsonl` schema (one line per superseded grade):
```json
{ ...full_grading_payload, "superseded_at": "ISO timestamp", "revision_reason": "..." }
```

Once the first grade is saved, the `reveal` endpoint becomes unlockable.
The candidate score endpoint (`GET /sessions/{code}/{cid}/score`) always serves the
latest grade — revision history is not exposed to candidates.

---

### `POST /sessions/{code}/reveal`
**Who:** HM dashboard (after clicking "Reveal")
**What:** Record that identity was revealed. Only permitted if the session is graded.

Returns `403 Forbidden` if not yet graded — this is the technical enforcement of
grade-before-reveal.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "revealed_at": "2026-04-13T10:52:09Z",
  "delta": "4.8 minutes after grade was recorded"
}
```

---

### `POST /sessions/{code}/comment`
**Who:** HM dashboard
**What:** Append a comment to the session.

Request body:
```json
{ "text": "Strong systems thinking. Invite to next round." }
```

Response `200 OK`:
```json
{
  "id": "c1",
  "text": "Strong systems thinking. Invite to next round.",
  "created_at": "2026-04-13T11:05:00Z"
}
```

Comments are append-only. There is no delete or edit endpoint.

---

### `POST /sessions/{code}/decision`
**Who:** HM dashboard
**What:** Record a hire/reject/next-round decision.

Request body:
```json
{
  "decision": "next_round",
  "reason": "Strong decomposition, want to see system design."
}
```

`decision` must be one of: `hire`, `next_round`, `reject`.

Response `200 OK`:
```json
{ "code": "INT-4829-XK", "decision": "next_round", "recorded_at": "2026-04-13T11:10:00Z" }
```

Decision is immutable after the first save.

---

### `GET /sessions/{code}/{cid}/score`
**Who:** Candidate (after submission, to check their score)
**Auth:** None — open route. The candidate knows their own cid.
**What:** Return the candidate's score, filtered by the HM's sharing config.

The `cid` is derived locally:
- GitHub auth: `sha256("github:{github_id}")[:12]`
- Email fallback: `sha256(email.lower())[:12]`

Both are available in `~/.interview/sessions/<code>/manifest.json` after `/submit`.
The CLI command `interview score <CODE>` computes this automatically.

Response `200 OK` when score sharing is enabled and session is graded:
```json
{
  "available": true,
  "overall_score": 7.5,
  "dimensions": [
    { "name": "Problem Decomposition", "score": 8, "justification": "..." }
  ],
  "summary": "Strong systems thinking...",
  "standout_moments": ["Caught the edge case early..."],
  "concerns": ["Tests were thin..."],
  "debrief": "You did well on X but missed Y..."
}
```

Fields present depend on the sharing config:
| `score` level | Fields returned |
|---|---|
| `none` | `{"available": false, "reason": "..."}` |
| `overall` | `available`, `overall_score` |
| `breakdown` | + `dimensions` |
| `breakdown_notes` | + `summary`, `standout_moments`, `concerns` |

`debrief` is always included in the response when available — it's Claude's analysis
of the session, not the HM's evaluation, so it's not an HM toggle.

Returns `404` if the interview code or cid is not found.

---

### `GET /sessions/{code}/{cid}/sharing`
**Who:** HM dashboard
**Auth:** hm_key required
**What:** Return the current sharing config for this interview code.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "sharing": {
    "score": "breakdown_notes"
  }
}
```

---

### `POST /sessions/{code}/sharing`
**Who:** HM dashboard (per-interview sharing controls)
**Auth:** hm_key required
**What:** Update the sharing config for this interview code. Takes effect immediately
for all candidates in this interview. Does not require a `cid` — sharing is per-interview,
not per-candidate.

Request body:
```json
{
  "sharing": {
    "score": "breakdown"
  }
}
```

`score` must be one of: `none`, `overall`, `breakdown`, `breakdown_notes`.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "sharing": { "score": "breakdown" }
}
```

Each change is written to a per-code sharing override file and audit-logged.
The interview payload's default `sharing` config (set at creation time) is used
if no override file exists.

---

## Data storage

The relay stores one directory per session:

```
/data/hms/<hm_key>/
  interviews/
    INT-4829-XK.json           — interview payload (problem, rubric, sharing config)
  sessions/
    INT-4829-XK/
      <cid>/
        manifest.json
        events.jsonl
        report.html            (if submitted)
        report.json            (if submitted)
        debrief.txt            (Claude's session debrief, if generated)
        grading.json           (written on POST /grade)
        comments.jsonl         (append-only)
        decision.json          (written on POST /decision)
        audit.jsonl            (every action, hash-chained)
        meta.json              (submitted_at, revealed_at, github identity, etc.)
  sharing/
    INT-4829-XK.json           (sharing config override — written by POST /sessions/{code}/sharing)
    INT-4829-XK_audit.jsonl    (audit log for sharing changes)
```

All files are written atomically (write to temp, rename). The `/data` directory is the
only thing that needs to be backed up.

---

## Audit log

Every state-changing action appended to `audit.jsonl` with a SHA-256 hash chain:

```jsonl
{"type":"session_submitted","code":"INT-4829-XK","ts":"2026-04-13T10:32:00Z","prev_hash":"0000","hash":"a1b2..."}
{"type":"grade_recorded",   "code":"INT-4829-XK","ts":"2026-04-13T10:47:22Z","prev_hash":"a1b2","hash":"c3d4..."}
{"type":"identity_revealed","code":"INT-4829-XK","ts":"2026-04-13T10:52:09Z","prev_hash":"c3d4","hash":"e5f6..."}
```

The chain is verifiable with `GET /audit/verify`.

---

### `GET /audit/verify`
**Who:** HM or compliance team
**What:** Walk the entire audit chain and report integrity status.

Response `200 OK`:
```json
{ "ok": true, "entries": 47, "message": "Chain intact." }
```

Or if tampered:
```json
{ "ok": false, "entries": 47, "message": "Hash mismatch at entry 23." }
```

---

## Error responses

All errors follow the same shape:

```json
{ "error": "session_not_found", "message": "No session found for INT-XXXX." }
```

| Status | Code | Meaning |
|--------|------|---------|
| 400 | `invalid_payload` | Missing required fields or malformed JSON |
| 401 | `unauthorized` | Missing or invalid API key |
| 403 | `not_graded` | Reveal attempted before grade was saved |
| 404 | `session_not_found` | No session for this code |
| 404 | `interview_not_found` | No interview for this code |
| 409 | `already_exists` | Session already submitted (immutable) |
| 409 | `already_graded` | Grade already recorded (immutable) |

---

## Deployment

```bash
docker run -d \
  --name interviewsignal-relay \
  -p 8080:8080 \
  -e RELAY_API_KEY=your-secret-key \
  -v /path/to/data:/data \
  interviewsignal/relay:latest
```

Point candidates and HMs at it:

```bash
interview configure-relay  # prompts for relay_url and api_key
```

Stored in `~/.interview/config.json`:
```json
{
  "relay_url": "https://interviews.internal.yourco.com",
  "relay_api_key": "your-secret-key"
}
```

---

## What the relay does not do

- **No grading.** The HM's dashboard runs grading locally using their own Anthropic API key
  and posts the result. The relay stores it.
- **No email.** The relay does not send anything. Notifications are out of scope for v1.
- **No decryption.** Session payloads are stored as-is. The relay has no access to problem
  content, rubrics, or candidate details beyond the code.
- **No user accounts.** One API key, one relay, one team. Multi-tenant is Phase 3.

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
  "manifest_json":  "<base64-encoded manifest.json>",
  "events_jsonl":   "<base64-encoded events.jsonl>",
  "report_html":    "<base64-encoded report.html>",
  "report_json":    "<base64-encoded report.json>"
}
```

- `manifest_json` and `events_jsonl` are required. The relay rejects submissions without them.
- `report_html` and `report_json` are optional — if absent, the HM can still grade and a report
  can be regenerated from the raw session data.
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
  "manifest": { "elapsed_minutes": 47, "event_count": 38, ... },
  "report": { "overall_score": null, "dimensions": [], ... },
  "grading": null,
  "comments": [],
  "decision": null,
  "revealed": false,
  "audit_entries": []
}
```

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
**Who:** HM dashboard (after clicking "Grade")
**What:** Save a grading result. The dashboard runs grading locally using the HM's API key
and posts the result here for persistence and audit logging.

Request body (JSON) — same schema as `grading.json`:
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
{ "code": "INT-4829-XK", "graded_at": "2026-04-13T10:47:22Z" }
```

Once a grade is saved, the `revealed` field becomes unlockable. Grading is immutable after
the first save — subsequent POSTs return `409 Conflict`.

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

## Data storage

The relay stores one directory per session:

```
/data/sessions/
  INT-4829-XK/
    manifest.json
    events.jsonl
    report.html          (if submitted)
    report.json          (if submitted)
    grading.json         (written on POST /grade)
    comments.jsonl       (append-only)
    decision.json        (written on POST /decision)
    audit.jsonl          (every action, hash-chained)
    meta.json            (submitted_at, revealed_at, etc.)
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

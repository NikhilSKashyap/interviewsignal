# Relay API Contract

The relay is an HTTP server that connects candidates to hiring managers. When `relay_url` is set
in config, all submissions route through it. Without it, the system falls back to email — fully
backward compatible for single-candidate workflows.

The relay is deliberately dumb: it stores sealed session packages and serves them back. It does
not grade. It does not send email. It does not decrypt anything. Grading is always HM-side,
using the HM's own Anthropic API key.

---

## Authentication

The relay uses two auth models:

**HM key (`hm_key`):** Each HM registers once via `POST /register` and receives a unique UUID.
All HM-gated routes require `Authorization: Bearer <hm_key>`. Sessions, interviews, and sharing
configs are namespaced under this key — no HM can access another's data.

**Master key (`RELAY_API_KEY`):** Operator-level access. Set via environment variable at relay
startup. Accepts the master key in place of any `hm_key`. Used for relay administration only;
HMs never set or use this key.

**Open routes (no auth):** `POST /register`, `GET /interviews/{code}`, `GET /auth/github/*`,
and `GET /sessions/{code}/{cid}/score` require no authorization header.

Requests to auth-gated routes with a missing or invalid token return:
```json
{ "error": "unauthorized", "message": "Valid hm_key required." }
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_API_KEY` | (none) | Master operator key. If unset, master key auth is disabled (dev mode). |
| `RELAY_DATA_DIR` | `/data` | Root directory for all stored data. |
| `RELAY_PORT` | `8080` | Listening port. |
| `RELAY_BASE_URL` | (auto-detected) | Public base URL for building OAuth redirect URIs. |
| `GITHUB_CLIENT_ID` | (none) | GitHub OAuth app client ID. Required for GitHub OAuth. |
| `GITHUB_CLIENT_SECRET` | (none) | GitHub OAuth app client secret. Required for GitHub OAuth. |

Future variables (planned for auto-grading):
| `GRADING_API_KEY` | (none) | Anthropic key for server-side auto-grading on submission. |
| `GRADING_MODEL` | (TBD) | Model to use for server-side grading. |

---

## Open endpoints

### `GET /healthz`
Health check. No auth required.

Response `200 OK`:
```json
{ "status": "ok" }
```

---

### `POST /register`
Register as a new HM. No auth required. Returns a unique `hm_key` scoped to this HM.
Run once per HM. `interview configure-relay` calls this automatically.

Response `201 Created`:
```json
{ "hm_key": "550e8400-e29b-41d4-a716-446655440000" }
```

---

### `GET /interviews/{code}`
Fetch an interview package by code. No auth required — candidates call this to bootstrap their
session. The package includes the problem, rubric, relay_url, hm_key, sharing config, and more.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "problem": "Build a rate limiter...",
  "rubric": "Score on: decomposition, edge cases, ...",
  "hm_email": "alice@company.com",
  "time_limit_minutes": 60,
  "anonymize": false,
  "sharing": { "score": "breakdown_notes" },
  "relay_url": "https://relay.interviewsignal.dev",
  "hm_key": "550e8400-...",
  "created_at": 1744754400
}
```

Returns `404` if the code is not registered.

---

### `GET /auth/github/start?code={code}`
Initiate GitHub OAuth for a candidate. No auth required. Returns the authorization URL to open
in the candidate's browser.

Returns `501` if GitHub OAuth is not configured on this relay (`GITHUB_CLIENT_ID` not set).

Response `200 OK` (when configured):
```json
{
  "url": "https://github.com/login/oauth/authorize?client_id=...&state=...&scope=read:user",
  "state": "uuid-state-token"
}
```

---

### `GET /auth/github/callback`
GitHub OAuth callback. GitHub redirects here after authorization. Exchanges the code for an
access token, fetches the GitHub profile, stores the result, and returns an HTML page.
Candidate CLI polls `/auth/github/poll` to get the result — this endpoint is browser-only.

---

### `GET /auth/github/poll?state={state}`
Candidate CLI polls this after opening the GitHub auth URL. Returns the current status.

Response when pending:
```json
{ "status": "pending" }
```

Response when complete:
```json
{
  "status": "complete",
  "github_id": 12345678,
  "github_username": "janedoe",
  "github_name": "Jane Doe",
  "avatar_url": "https://avatars.githubusercontent.com/u/12345678",
  "session_token": "uuid-state-token",
  "github_token": "gho_..."
}
```

The `session_token` is the state UUID. The candidate CLI uses it as auth when calling
`POST /sessions`. The `github_token` is used by the candidate CLI to create the GitHub repo —
it is never written to `manifest.json` or stored on the relay.

Response when duplicate (already submitted):
```json
{
  "status": "duplicate",
  "github_username": "janedoe",
  "message": "You have already submitted for this interview."
}
```

---

### `GET /sessions/{code}/{cid}/score`
Candidate fetches their own score. No auth required. The `cid` is derived locally:
- GitHub auth: `sha256("github:{github_id}")[:12]`
- Email fallback: `sha256(email.lower())[:12]`

Both are available in `~/.interview/sessions/<code>/manifest.json` after `/submit`.
The CLI command `interview score <CODE>` computes this automatically.

Response when score sharing is disabled or session not yet graded:
```json
{ "available": false, "reason": "Score sharing is not enabled for this interview." }
```

Response when score is available (fields depend on sharing level):
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

Fields returned by sharing level:

| `score` config | Fields returned |
|---|---|
| `none` | `{"available": false, "reason": "..."}` |
| `overall` | `available`, `overall_score` |
| `breakdown` | + `dimensions` |
| `breakdown_notes` | + `summary`, `standout_moments`, `concerns` |

`debrief` is always included when available — it is Claude's analysis of the session, not the
HM's evaluation, and is not an HM toggle.

Returns `404` if the interview code or cid is not found.

---

## HM-gated endpoints

All require `Authorization: Bearer <hm_key>`.

### `POST /interviews`
Push an interview package to the relay. Called by `setup.create_interview()` when a relay is
configured. The `payload_b64` field is the base64-encoded interview JSON.

Request body:
```json
{
  "code": "INT-4829-XK",
  "payload_b64": "<base64-encoded interview JSON>"
}
```

Response `201 Created`:
```json
{ "code": "INT-4829-XK", "registered_at": "2026-04-19T10:00:00Z" }
```

Returns `409` if the code is already registered.

---

### `POST /sessions`
Candidate submits a sealed session package. The `hm_key` must match the owner of the interview
code. If GitHub OAuth is configured on the relay, `session_token` is required.

Request body:
```json
{
  "code": "INT-4829-XK",
  "candidate_email": "jane@example.com",
  "candidate_name": "Jane Doe",
  "session_token": "uuid-state-token",
  "github_repo_url": "https://github.com/janedoe/interview-INT-4829-XK",
  "manifest_json": "<base64-encoded manifest.json>",
  "events_jsonl":  "<base64-encoded events.jsonl>",
  "report_html":   "<base64-encoded report.html>",
  "report_json":   "<base64-encoded report.json>",
  "debrief_txt":   "<base64-encoded debrief.txt>"
}
```

- `manifest_json` and `events_jsonl` are required. All other fields are optional.
- `session_token` is required when GitHub OAuth is configured on the relay.
- `github_repo_url` is omitted if repo creation failed or OAuth is not configured.
- Returns `401` with `github_auth_required` if OAuth is configured but `session_token` is missing.
- Returns `409` if this candidate has already submitted for this code.
- Returns `403` if the code belongs to a different HM.
- Returns `413` if the request body exceeds 200 MB (base64 overhead above the 100 MB session limit).

Response `201 Created`:
```json
{
  "code": "INT-4829-XK",
  "cid": "abc123def456",
  "submitted_at": "2026-04-19T10:32:00Z"
}
```

---

### `GET /sessions`
List all interviews and candidates for this HM.

Response `200 OK`:
```json
{
  "interviews": [
    {
      "code": "INT-4829-XK",
      "title": "Build a rate limiter...",
      "created_at": 1744754400,
      "time_limit_minutes": 60,
      "anonymize": false,
      "candidate_count": 3,
      "candidates": [
        {
          "cid": "abc123def456",
          "submitted_at": "2026-04-19T10:32:00Z",
          "elapsed_minutes": 47,
          "overall_score": 7.5,
          "event_count": 38,
          "graded": true,
          "revealed": false,
          "github_username": "janedoe",
          "github_repo_url": "https://github.com/janedoe/interview-INT-4829-XK",
          "candidate_name": "Jane Doe",
          "avatar_url": "https://avatars.githubusercontent.com/u/12345678"
        }
      ]
    }
  ]
}
```

Identity fields (`github_username`, `candidate_name`, `avatar_url`, `github_repo_url`) are
always populated — there is no reveal gate. `revealed` in `meta.json` is kept for historical
compatibility but has no behavioural effect.

---

### `GET /sessions/{code}`
List candidates for one interview code.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "candidates": [ ... ]
}
```

---

### `GET /sessions/{code}/{cid}`
Full session detail for one candidate.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "cid": "abc123def456",
  "submitted_at": "2026-04-19T10:32:00Z",
  "graded_at": "2026-04-19T11:15:00Z",
  "elapsed_minutes": 47,
  "candidate_email": "jane@example.com",
  "candidate_name": "Jane Doe",
  "github_username": "janedoe",
  "github_repo_url": "https://github.com/janedoe/interview-INT-4829-XK",
  "avatar_url": "https://avatars.githubusercontent.com/u/12345678",
  "manifest": { "event_count": 38, "elapsed_minutes": 47, ... },
  "report": { "overall_score": null, ... },
  "grading": {
    "dimensions": [...],
    "overall_score": 7.5,
    "summary": "...",
    "standout_moments": [...],
    "concerns": [...],
    "graded_at": "2026-04-19T11:15:00Z"
  },
  "grading_history": [],
  "comments": [],
  "decision": null,
  "audit_entries": [...]
}
```

Identity fields are always populated — not gated on a reveal flag.

---

### `GET /sessions/{code}/{cid}/events`
Raw `events.jsonl` content. Returns `text/plain`, one JSON object per line. The dashboard
downloads this to the local sessions directory so `grader.py` can read it for grading.

---

### `GET /sessions/{code}/{cid}/report.html`
The HTML report. Returns `text/html`.

---

### `GET /sessions/{code}/<anything>/sharing`
Return the current sharing config for this interview code. The `cid` segment in the URL is
ignored — sharing is per-interview-code, not per-candidate.

Response `200 OK`:
```json
{ "code": "INT-4829-XK", "sharing": { "score": "breakdown_notes" } }
```

---

### `POST /sessions/{code}/{cid}/grade`
Save or revise a grading result. The dashboard runs grading locally and posts the result here.

**First grade** — request body:
```json
{
  "dimensions": [
    { "name": "Problem Decomposition", "score": 8, "justification": "..." }
  ],
  "overall_score": 7.5,
  "summary": "Strong systems thinking...",
  "standout_moments": ["Caught the edge case early"],
  "concerns": ["Tests were thin"]
}
```

Response `200 OK`:
```json
{ "code": "INT-4829-XK", "cid": "abc123def456", "graded_at": "2026-04-19T11:15:00Z" }
```

**Grade revision** — include a `reason` field:
```json
{
  "dimensions": [...],
  "overall_score": 8.2,
  "summary": "...",
  "reason": "Undervalued the store abstraction on first read."
}
```

If the session is already graded and `reason` is missing or empty:
```json
{ "error": "revision_requires_reason", "message": "Grade revision requires a 'reason' field explaining the change." }
```

Response `200 OK` for a revision:
```json
{
  "code": "INT-4829-XK",
  "cid": "abc123def456",
  "graded_at": "2026-04-19T11:30:00Z",
  "revision": true,
  "previous_score": 7.5,
  "new_score": 8.2
}
```

The previous grade is moved to `grading_history.jsonl` before `grading.json` is overwritten.
Grade revision history is never exposed to candidates via the score endpoint.

---

### `POST /sessions/{code}/{cid}/reveal`
No-op. Returns `200 OK` and does nothing. Identity is always visible; this endpoint exists
only for API compatibility with older dashboard versions.

Response `200 OK`:
```json
{
  "code": "INT-4829-XK",
  "cid": "abc123def456",
  "candidate_email": "jane@example.com",
  "github_username": "janedoe",
  "avatar_url": "https://avatars.githubusercontent.com/u/12345678"
}
```

---

### `POST /sessions/{code}/{cid}/comment`
Append a comment to the session. Comments are append-only — no edit or delete.

Request body:
```json
{ "text": "Strong systems thinking. Invite to next round." }
```

Response `200 OK`:
```json
{
  "id": "c1",
  "text": "Strong systems thinking. Invite to next round.",
  "created_at": "2026-04-19T11:05:00Z"
}
```

---

### `POST /sessions/{code}/{cid}/decision`
Record a hire/reject/next-round decision. Immutable after the first write.

Request body:
```json
{ "decision": "next_round", "reason": "Strong decomposition, want to see system design." }
```

`decision` must be one of: `hire`, `next_round`, `reject`.

Response `200 OK`:
```json
{ "code": "INT-4829-XK", "cid": "abc123def456", "decision": "next_round", "recorded_at": "2026-04-19T11:10:00Z" }
```

Returns `409 already_decided` if a decision has already been recorded.

---

### `POST /sessions/{code}/sharing`
Update the sharing config for an interview code. Applies to all candidates in this interview.
Does not require a `cid`. Each change is audit-logged.

Request body (either form accepted):
```json
{ "sharing": { "score": "breakdown" } }
```
or:
```json
{ "score": "breakdown" }
```

`score` must be one of: `none`, `overall`, `breakdown`, `breakdown_notes`.

Response `200 OK`:
```json
{ "code": "INT-4829-XK", "sharing": { "score": "breakdown" } }
```

The interview payload's default `sharing` config (set at creation time) is used as the fallback
if no override file exists. The override file takes precedence.

---

### `GET /audit/verify`
Walk the entire per-session `audit.jsonl` for all sessions belonging to this HM and verify
every hash chain.

Response `200 OK` (intact):
```json
{ "ok": true, "entries": 47, "message": "Chain intact." }
```

Response `200 OK` (broken):
```json
{ "ok": false, "entries": 47, "message": "Hash mismatch: INT-4829-XK/abc123def456 entry 3: expected 9f2c1a3b, got deadbeef" }
```

---

## Data storage

```
/data/
  code_index.json                    — {code: hm_key} global lookup
  github_submissions.json            — {code: {github_id: cid}} duplicate prevention
  github_auth/
    <state-uuid>.json                — pending/complete/expired OAuth state records
  hms/
    <hm_key>/
      info.json                      — {hm_key, registered_at}
      interviews/
        <code>.json                  — full interview payload
      sessions/
        <code>/
          <cid>/
            manifest.json
            events.jsonl
            report.html
            report.json
            debrief.txt
            grading.json             — current grading result
            grading_history.jsonl    — superseded grades (one per line)
            comments.jsonl           — append-only comments
            decision.json            — hire/next_round/reject
            audit.jsonl              — hash-chained HM action log
            meta.json                — submitted_at, github identity, graded flag
      sharing/
        <code>.json                  — sharing config override
        <code>_audit.jsonl           — audit log for sharing changes
```

All files are written atomically (write to `.tmp`, then rename). The `/data` directory is the
only thing that needs to be backed up.

**Size limits:**
- Request body: 200 MB (base64 adds ~33% overhead over the 100 MB session limit)
- Per session: 100 MB
- Per individual file: 20 MB

---

## Audit log format

Every state-changing action appended to `audit.jsonl` with SHA-256 hash chain:

```jsonl
{"type":"session_submitted","code":"INT-4829-XK","cid":"abc123","ts":"2026-04-19T10:32:00Z","prev_hash":"0000000000000000","hash":"a1b2c3d4e5f60001"}
{"type":"grade_recorded",   "code":"INT-4829-XK","cid":"abc123","ts":"2026-04-19T11:15:00Z","prev_hash":"a1b2c3d4e5f60001","hash":"b2c3d4e5f6070002"}
```

Verifiable via `GET /audit/verify`.

---

## Error responses

All errors follow the same shape:
```json
{ "error": "session_not_found", "message": "No session for INT-4829-XK/abc123def456." }
```

| Status | Code | Meaning |
|--------|------|---------|
| 400 | `invalid_payload` | Missing required fields or malformed JSON |
| 400 | `revision_requires_reason` | Grade revision missing reason field |
| 401 | `unauthorized` | Missing or invalid hm_key |
| 401 | `github_auth_required` | Relay requires GitHub OAuth but session_token missing |
| 401 | `invalid_session_token` | session_token not found or not in complete state |
| 403 | `forbidden` | Code belongs to a different HM |
| 403 | `token_mismatch` | session_token was issued for a different interview code |
| 404 | `not_found` | Route not found |
| 404 | `session_not_found` | No session for this code/cid |
| 404 | `interview_not_found` | No interview for this code |
| 404 | `file_not_found` | Requested file not found for this session |
| 409 | `already_exists` | Interview code already registered |
| 409 | `already_submitted` | This candidate (or GitHub account) has already submitted |
| 409 | `already_decided` | Decision already recorded (immutable) |
| 413 | `payload_too_large` | Request body exceeds 200 MB |
| 501 | (JSON body) | GitHub OAuth requested but not configured on this relay |

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

With GitHub OAuth:
```bash
docker run -d \
  --name interviewsignal-relay \
  -p 8080:8080 \
  -e RELAY_API_KEY=your-secret-key \
  -e GITHUB_CLIENT_ID=your-client-id \
  -e GITHUB_CLIENT_SECRET=your-client-secret \
  -e RELAY_BASE_URL=https://relay.example.com \
  -v /path/to/data:/data \
  interviewsignal/relay:latest
```

Or with Docker Compose:
```bash
docker compose up
```

HMs configure their relay once:
```bash
interview configure-relay   # prompts for relay URL → auto-registers hm_key
```

---

## What the relay does not do

- **No grading.** Grading runs on the HM's machine using their Anthropic API key. The relay stores the result.
- **No email.** The relay sends nothing. Notifications are out of scope.
- **No decryption.** Session payloads are stored as-is.
- **No real-time monitoring.** Sessions are visible only after submission.

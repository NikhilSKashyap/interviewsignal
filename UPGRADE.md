# InterviewSignal — Community Relay Upgrade

Migrate from self-hosted relay to a community-shared Vercel + Supabase backend.
HMs go from "set up a relay" to "pip install and open dashboard."
Grading stays local — no timeouts, no limits, HM brings their own API key.

---

## Architecture after upgrade

```
Candidate                 Community backend          HM machine
─────────                 ─────────────────          ──────────
pip install            →  Vercel API routes       ←  interview dashboard
/interview CODE        →  Supabase (sessions)     →  Grade / Grade All
/submit                →  Clerk (auth)            →  Local Claude API call
                                                  →  Write grade → Supabase
```

**What moves to Vercel + Supabase:**
- Assignment fetch (`/api/assignments/[code]`)
- Session submission (`/api/submit`)
- Interview creation and management
- Auth (Clerk, GitHub OAuth)
- Session storage (Supabase)

**What stays local:**
- `interview dashboard` — Python local server
- Grading — calls Claude API from HM's machine, writes result to Supabase
- No relay setup, no Fly.io, no Docker

**Self-hosted relay stays as a power-user option** for teams that need full data isolation.

---

## Phase 1 — Supabase schema

### 1.1 Create Supabase project
- Go to supabase.com → New project
- Save: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`

### 1.2 Run schema migrations

```sql
-- HM profiles (synced from Clerk on first login)
create table hm_profiles (
  id           uuid primary key default gen_random_uuid(),
  clerk_id     text unique not null,
  github_username text,
  github_avatar   text,
  api_key_enc  text,   -- Claude API key, encrypted at rest
  created_at   timestamptz default now()
);

-- Interviews
create table interviews (
  id                        uuid primary key default gen_random_uuid(),
  hm_id                     uuid references hm_profiles not null,
  code                      text unique not null,   -- INT-XXXX-XX
  problem                   text not null,
  rubric                    text not null,          -- never sent to candidates
  time_limit_minutes        int,
  reviewer_github_usernames text[] default '{}',
  retired_at                timestamptz,
  created_at                timestamptz default now()
);

-- Candidate sessions
create table sessions (
  id               uuid primary key default gen_random_uuid(),
  interview_id     uuid references interviews not null,
  code             text not null,
  candidate_email  text,
  candidate_name   text,
  github_username  text,
  github_avatar    text,
  github_repo_url  text,
  github_push_ok   bool default false,
  started_at       float,
  ended_at         float,
  elapsed_minutes  float,
  events           jsonb,       -- full event log array
  manifest         jsonb,       -- sealed manifest
  git_diff         text,
  commit_log       jsonb,
  final_hash       text,
  sealed           bool default false,
  created_at       timestamptz default now()
);

-- Grading results
create table grades (
  id               uuid primary key default gen_random_uuid(),
  session_id       uuid references sessions not null,
  overall_score    float,
  raw_score        float,
  overtime_penalty jsonb,
  dimensions       jsonb,
  summary          text,
  standout_moments text[],
  concerns         text[],
  model            text,
  graded_at        timestamptz default now()
);

-- Problem library upvotes
create table problem_votes (
  id           uuid primary key default gen_random_uuid(),
  problem_path text not null,   -- e.g. 'backend/rate-limiter'
  voter_ip     text,
  created_at   timestamptz default now(),
  unique(problem_path, voter_ip)
);
```

### 1.3 Row Level Security policies

```sql
-- HMs can only see their own data
alter table hm_profiles enable row level security;
alter table interviews   enable row level security;
alter table sessions     enable row level security;
alter table grades       enable row level security;

-- interviews: HM reads/writes own rows
create policy "hm_own_interviews" on interviews
  using (hm_id = (select id from hm_profiles where clerk_id = auth.uid()::text));

-- sessions: HM reads sessions for their interviews; candidates insert (open)
create policy "hm_read_sessions" on sessions
  using (interview_id in (
    select id from interviews
    where hm_id = (select id from hm_profiles where clerk_id = auth.uid()::text)
  ));
create policy "candidate_insert_session" on sessions
  for insert with check (true);

-- grades: HM reads/writes grades for their sessions
create policy "hm_own_grades" on grades
  using (session_id in (
    select s.id from sessions s
    join interviews i on s.interview_id = i.id
    join hm_profiles h on i.hm_id = h.id
    where h.clerk_id = auth.uid()
  ));

-- votes: open read and insert
alter table problem_votes enable row level security;
create policy "votes_read"   on problem_votes for select using (true);
create policy "votes_insert" on problem_votes for insert with check (true);
```

---

## Phase 2 — Vercel project setup

### 2.1 Create web directory

```
interview/
  web/                     ← new Vercel project root
    api/
      assignments/
        [code].js          ← GET  candidate fetches assignment
      submit.js            ← POST candidate submits session
      interviews/
        index.js           ← GET list / POST create (auth)
        [code].js          ← GET one / DELETE retire (auth)
      sessions/
        index.js           ← GET HM sessions (auth)
        [id].js            ← GET one session (auth)
      votes/
        [problem].js       ← GET count / POST vote
      user/
        sync.js            ← POST sync Clerk user → hm_profiles
    public/
      index.html           ← landing page
      problems.html        ← problems library
      install.sh           ← one-liner install script
    package.json
    vercel.json
```

### 2.2 Install dependencies

```bash
cd web
npm init -y
npm install @supabase/supabase-js @clerk/clerk-sdk-node
```

### 2.3 vercel.json

```json
{
  "rewrites": [
    { "source": "/api/(.*)", "destination": "/api/$1" }
  ]
}
```

### 2.4 Set Vercel environment variables

```
SUPABASE_URL
SUPABASE_SERVICE_KEY      ← server-side only (never expose to client)
CLERK_SECRET_KEY
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
```

---

## Phase 3 — Vercel API routes

### 3.1 GET /api/assignments/[code].js
- Open endpoint (no auth)
- Fetch from `interviews` table where `code = params.code` and `retired_at is null`
- Return `{problem, time_limit_minutes, relay_url}` — **never return rubric**
- Same response shape as current relay `/assignments/<code>`

### 3.2 POST /api/submit.js
- Open endpoint (no auth — candidate submits)
- Validate `submit_token` against interview
- Insert row into `sessions` table
- Return `{ok: true, code}`
- No grading triggered — grading is on-demand from dashboard

### 3.3 GET /api/interviews/index.js
- Auth required (Clerk JWT)
- Fetch interviews for authenticated HM
- Return list with session counts

### 3.4 POST /api/interviews/index.js
- Auth required
- Generate `INT-XXXX-XX` code
- Insert into `interviews` table
- Return `{code}`

### 3.5 GET /api/sessions/index.js
- Auth required
- Fetch sessions for HM's interviews
- Join with grades table for scores
- Return list (manifest without rubric)

### 3.6 GET /api/votes/[problem].js + POST
- Open
- GET: `select count(*) from problem_votes where problem_path = params.problem`
- POST: insert vote (dedup by IP)

---

## Phase 4 — Clerk auth

### 4.1 Create Clerk project
- clerk.com → New application → GitHub OAuth only
- Copy `CLERK_SECRET_KEY` and `PUBLISHABLE_KEY`

### 4.2 Sync Clerk user to Supabase on first login
- Clerk webhook → `POST /api/user/sync`
- Creates row in `hm_profiles` if not exists
- Stores `github_username`, `github_avatar`

### 4.3 Protect HM API routes
- All `/api/interviews/*` and `/api/sessions/*` require valid Clerk JWT
- Use `@clerk/clerk-sdk-node` `requireAuth()` middleware

---

## Phase 5 — Update Python package

### 5.1 core/transport.py
- Default relay URL: `https://interviewsignal.vercel.app/api`
- Community relay used unless HM has configured a custom relay
- No change to the transport interface — same `get_transport()` call

### 5.2 dashboard/serve.py
- Replace local file reads (`~/.interview/sessions/`) with Supabase client calls
- HM authenticates via Clerk in browser → JWT stored in session cookie
- Dashboard passes JWT to Supabase for RLS-protected queries
- Grading flow unchanged — local Python calls Claude API, writes grade to Supabase via `grades` table

### 5.3 core/setup.py
- `load_assignment(code)` fetches from `interviewsignal.vercel.app/api/assignments/<code>`
- Fallback to configured relay URL if set

### 5.4 Supabase client helper
New file: `interview/core/supabase_client.py`
- Thin wrapper around Supabase REST API (stdlib urllib, no external deps)
- Used by dashboard only (not by candidate-side code)

---

## Phase 6 — Vercel frontend

### 6.1 Restructure worked/ by category

```
worked/
  backend/
    rate-limiter/
      PROBLEM.md
      RUBRIC.md
    agent-task-queue/
    webhook-delivery/
  mle/
    (problems to add)
  frontend/
    (problems to add)
```

### 6.2 Landing page (web/public/index.html)
- Hero: one-liner pitch
- Install one-liner code block
- Comparison table (Saffron / OpenRound / InterviewSignal)
- Link to problems library
- Link to GitHub
- "Sign in" → Clerk → dashboard

### 6.3 Problems library (web/public/problems.html)
- Parse `worked/` folder structure at build time → `problems.json`
- Cards: title + category tag
- Click to expand: problem statement + rubric, copy buttons
- Filter by category (client-side JS)
- Upvote button → `POST /api/votes/[problem]`
- Vercel build step generates `problems.json` from markdown files

### 6.4 Install script (web/public/install.sh)

```bash
#!/bin/bash
set -e
echo "Installing InterviewSignal..."
pip install interviewsignal
interview install
echo ""
echo "Done. Start your session:"
echo "  /interview <CODE>"
```

Hosted at `https://interviewsignal.vercel.app/install.sh`

---

## Phase 7 — Bulk candidate invite

### 7.1 CSV upload in dashboard
- HM uploads `candidates.csv` (email column)
- Dashboard generates one email per candidate:
  ```
  Subject: Your InterviewSignal session — INT-4829-XK
  
  Install:  pip install interviewsignal && interview install
  Start:    /interview INT-4829-XK
  Submit:   /submit when done
  ```
- "Copy all" or "Download .txt" — HM pastes into their own email client
- No SMTP required

---

## Phase 8 — Testing and deploy

### 8.1 Test locally
```bash
vercel dev          # runs Vercel API routes locally
interview dashboard # connects to local Vercel dev
```

### 8.2 Deploy
```bash
vercel --prod
```

Live at `https://interviewsignal.vercel.app`

### 8.3 Smoke test
- Create interview from dashboard
- Run `/interview CODE` as candidate
- `/submit`
- Verify session appears in dashboard
- Grade one session
- Verify grade saved

---

## Phase 9 — Update README and package

- README: update relay setup section → point to community relay
- README: add "zero setup" HM quickstart
- `pyproject.toml`: bump to `0.10.0` (breaking: default relay changes)
- Keep self-hosted relay docs for power users

---

## What does NOT change

- `interview/hooks/` — all hook code untouched
- `interview/core/session.py` — session start/seal unchanged
- `interview/core/grader.py` — grading logic unchanged
- `interview/core/flags.py` — flags unchanged
- `interview/core/integrity.py` — hash chain unchanged
- Candidate CLI flow — `/interview CODE` and `/submit` unchanged
- Self-hosted relay — still works, still documented

---

## Costs at scale

| Service     | Free tier limit              | Hits limit when         |
|:------------|:-----------------------------|:------------------------|
| Vercel      | 100k function calls/mo       | ~10k interviews/mo      |
| Supabase    | 500MB, 50k rows              | ~50k sessions           |
| Clerk       | 10k monthly active users     | You have traction       |

All $0 until meaningful scale.

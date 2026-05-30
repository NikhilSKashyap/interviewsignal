// GET  /api/sessions — HM fetches their sessions (auth required)
// POST /api/sessions — candidate submits session (open — called by Python relay client)

import { NextRequest, NextResponse } from 'next/server'
import { auth, currentUser } from '@clerk/nextjs/server'
import { supabaseAdmin } from '@/lib/supabase'

async function ensureProfile(userId: string): Promise<string | null> {
  const { data: existing } = await supabaseAdmin
    .from('hm_profiles').select('id').eq('clerk_id', userId).single()
  if (existing) return existing.id

  const user = await currentUser()
  const github = user?.externalAccounts?.find(a => a.provider === 'github')
  const { data: created, error } = await supabaseAdmin
    .from('hm_profiles')
    .insert({ clerk_id: userId, github_username: github?.username ?? null, github_avatar: user?.imageUrl ?? null })
    .select('id').single()
  if (error) return null
  return created.id
}

export async function GET() {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const hmId = await ensureProfile(userId)
  if (!hmId) return NextResponse.json({ error: 'Could not load profile' }, { status: 500 })

  const hm = { id: hmId }

  const { data, error } = await supabaseAdmin
    .from('sessions')
    .select(`
      id, code, candidate_name, candidate_email, github_username,
      github_avatar, github_repo_url, elapsed_minutes, sealed,
      final_hash, created_at,
      grades(overall_score, raw_score, overtime_penalty, summary, graded_at),
      interviews!inner(hm_id)
    `)
    .eq('interviews.hm_id', hm.id)
    .order('created_at', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json(data)
}

export async function POST(req: NextRequest) {
  // Candidate submission from Python relay client (RelayTransport.send)
  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const code = body.code as string
  if (!code) return NextResponse.json({ error: 'Missing code' }, { status: 400 })

  const { data: interview, error: iErr } = await supabaseAdmin
    .from('interviews')
    .select('id')
    .eq('code', code)
    .is('retired_at', null)
    .single()

  if (iErr || !interview) {
    return NextResponse.json({ error: 'Interview not found or expired' }, { status: 404 })
  }

  // Decode base64-encoded files sent by the Python client
  let manifest: Record<string, unknown> | null = null
  let events: unknown[] | null = null

  try {
    if (body.manifest_json) {
      manifest = JSON.parse(Buffer.from(body.manifest_json as string, 'base64').toString('utf-8'))
    }
    if (body.events_jsonl) {
      const raw = Buffer.from(body.events_jsonl as string, 'base64').toString('utf-8')
      events = raw.trim().split('\n').filter(Boolean).map(l => JSON.parse(l))
    }
  } catch {
    return NextResponse.json({ error: 'Could not decode session data' }, { status: 400 })
  }

  const { error: sErr } = await supabaseAdmin
    .from('sessions')
    .insert({
      interview_id:    interview.id,
      code,
      candidate_email: (manifest?.candidate_email ?? body.candidate_email ?? null) as string | null,
      candidate_name:  (manifest?.candidate_name  ?? body.candidate_name  ?? null) as string | null,
      github_username: (manifest?.github_username ?? body.github_username ?? null) as string | null,
      github_avatar:   (manifest?.github_avatar_url ?? null) as string | null,
      github_repo_url: (manifest?.github_repo_url  ?? null) as string | null,
      github_push_ok:  (manifest?.github_push_ok   ?? false) as boolean,
      started_at:      (manifest?.started_at        ?? null) as number | null,
      ended_at:        (manifest?.ended_at          ?? null) as number | null,
      elapsed_minutes: (manifest?.elapsed_minutes   ?? null) as number | null,
      events,
      manifest,
      git_diff:        (manifest?.git_diff          ?? null) as string | null,
      commit_log:      (manifest?.commit_log        ?? null),
      final_hash:      (manifest?.final_hash        ?? null) as string | null,
      sealed:          true,
    })

  if (sErr) {
    console.error('session insert error:', sErr)
    return NextResponse.json({ error: 'Failed to save session' }, { status: 500 })
  }

  return NextResponse.json({ ok: true, code, auto_graded: false })
}

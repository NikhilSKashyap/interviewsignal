// GET  /api/sessions — HM fetches sessions
//   Web dashboard (Clerk JWT): returns flat array
//   Local dashboard (hm_key):  returns nested {interviews:[{code,candidates:[]}]} format
// POST /api/sessions — candidate submits session (open)

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'
import { getHmId } from '@/lib/hmAuth'

export async function GET(req: NextRequest) {
  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const isHmKey = (req.headers.get('authorization') ?? '').startsWith('Bearer is_')

  const { data, error } = await supabaseAdmin
    .from('sessions')
    .select(`
      id, code, candidate_name, candidate_email, github_username,
      github_avatar, github_repo_url, elapsed_minutes, sealed,
      final_hash, started_at, ended_at, created_at,
      grades(overall_score, raw_score, overtime_penalty, summary, graded_at),
      interviews!inner(hm_id, problem, time_limit_minutes, retired_at)
    `)
    .eq('interviews.hm_id', hmId)
    .order('created_at', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  // Local dashboard expects nested format
  if (isHmKey) {
    const byCode: Record<string, { code: string; title: string; anonymize: boolean; retired_at: string | null; candidates: unknown[] }> = {}
    for (const s of (data ?? [])) {
      const iv = (s as Record<string, unknown>).interviews as Record<string, unknown>
      const code = s.code
      if (!byCode[code]) {
        byCode[code] = {
          code,
          title:      ((iv?.problem as string) ?? '').slice(0, 60),
          anonymize:  false,
          retired_at: (iv?.retired_at as string) ?? null,
          candidates: [],
        }
      }
      const grade = ((s as Record<string, unknown>).grades as Record<string, unknown>[])?.[0]
      byCode[code].candidates.push({
        cid:             s.id,   // use UUID as cid
        email:           s.candidate_email,
        name:            s.candidate_name,
        github_username: s.github_username,
        github_repo_url: s.github_repo_url,
        submitted_at:    s.ended_at,
        elapsed_minutes: s.elapsed_minutes,
        overall_score:   grade?.overall_score ?? null,
        final_hash:      s.final_hash,
      })
    }
    return NextResponse.json({ interviews: Object.values(byCode) })
  }

  return NextResponse.json(data)
}

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>
  try { body = await req.json() }
  catch { return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 }) }

  const code = body.code as string
  if (!code) return NextResponse.json({ error: 'Missing code' }, { status: 400 })

  const { data: interview, error: iErr } = await supabaseAdmin
    .from('interviews').select('id').eq('code', code).is('retired_at', null).single()

  if (iErr || !interview) {
    return NextResponse.json({ error: 'Interview not found or expired' }, { status: 404 })
  }

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

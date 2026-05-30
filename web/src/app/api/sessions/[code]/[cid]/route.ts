// GET /api/sessions/[code]/[cid]
// Returns session detail. cid is the Supabase session UUID.

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'
import { getHmId } from '@/lib/hmAuth'

type Params = { params: Promise<{ code: string; cid: string }> }

export async function GET(req: NextRequest, { params }: Params) {
  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { code, cid } = await params

  // cid can be the UUID or a special value like 'events.jsonl' / 'manifest.json'
  if (cid === 'events.jsonl' || cid === 'manifest.json') {
    // GET /sessions/{code}/events.jsonl or /sessions/{code}/manifest.json
    // Return the most recent session for this code
    const { data } = await supabaseAdmin
      .from('sessions')
      .select('events, manifest, interviews!inner(hm_id)')
      .eq('code', code)
      .eq('interviews.hm_id', hmId)
      .order('created_at', { ascending: false })
      .limit(1)
      .single()

    if (!data) return NextResponse.json({ error: 'Not found' }, { status: 404 })

    if (cid === 'events.jsonl') {
      const lines = ((data.events as unknown[]) ?? []).map(e => JSON.stringify(e)).join('\n')
      return new NextResponse(lines, { headers: { 'content-type': 'text/plain' } })
    }
    return NextResponse.json(data.manifest)
  }

  const { data, error } = await supabaseAdmin
    .from('sessions')
    .select(`
      id, code, candidate_name, candidate_email, github_username,
      github_avatar, github_repo_url, elapsed_minutes, sealed,
      final_hash, started_at, ended_at, created_at, events, manifest, git_diff, commit_log,
      grades(overall_score, raw_score, overtime_penalty, dimensions, summary, standout_moments, concerns, graded_at),
      interviews!inner(hm_id, problem, time_limit_minutes)
    `)
    .eq('id', cid)
    .eq('code', code)
    .eq('interviews.hm_id', hmId)
    .single()

  if (error || !data) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  return NextResponse.json({ ...data, cid: data.id })
}

// POST /api/submit
// Open endpoint — candidate submits sealed session.
// Validates submit_token, writes session to Supabase.
// Grading is on-demand (HM clicks Grade in dashboard).

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 })
  }

  const code = body.code as string
  if (!code) {
    return NextResponse.json({ error: 'Missing code' }, { status: 400 })
  }

  // Fetch interview to validate and get interview_id
  const { data: interview, error: iErr } = await supabaseAdmin
    .from('interviews')
    .select('id, code')
    .eq('code', code)
    .is('retired_at', null)
    .single()

  if (iErr || !interview) {
    return NextResponse.json({ error: 'Interview not found or expired' }, { status: 404 })
  }

  // Insert session row
  const { error: sErr } = await supabaseAdmin
    .from('sessions')
    .insert({
      interview_id:    interview.id,
      code:            code,
      candidate_email: body.candidate_email  ?? null,
      candidate_name:  body.candidate_name   ?? null,
      github_username: body.github_username  ?? null,
      github_avatar:   body.github_avatar    ?? null,
      github_repo_url: body.github_repo_url  ?? null,
      github_push_ok:  body.github_push_ok   ?? false,
      started_at:      body.started_at       ?? null,
      ended_at:        body.ended_at         ?? null,
      elapsed_minutes: body.elapsed_minutes  ?? null,
      events:          body.events           ?? null,
      manifest:        body.manifest         ?? null,
      git_diff:        body.git_diff         ?? null,
      commit_log:      body.commit_log       ?? null,
      final_hash:      body.final_hash       ?? null,
      sealed:          true,
    })

  if (sErr) {
    console.error('submit error:', sErr)
    return NextResponse.json({ error: 'Failed to save session' }, { status: 500 })
  }

  return NextResponse.json({ ok: true, code })
}

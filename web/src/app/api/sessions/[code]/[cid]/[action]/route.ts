// GET  /api/sessions/[code]/[cid]/events.jsonl  → raw events
// GET  /api/sessions/[code]/[cid]/manifest.json → raw manifest
// POST /api/sessions/[code]/[cid]/grade         → save grade
// POST /api/sessions/[code]/[cid]/score         → candidate score (open)

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'
import { getHmId } from '@/lib/hmAuth'

type Params = { params: Promise<{ code: string; cid: string; action: string }> }

export async function GET(req: NextRequest, { params }: Params) {
  const { code, cid, action } = await params

  // score is open (candidate can fetch their own)
  if (action === 'score') {
    const { data } = await supabaseAdmin
      .from('sessions')
      .select('grades(overall_score, summary)')
      .eq('id', cid)
      .eq('code', code)
      .single()

    const grade = (data as Record<string, unknown>)?.grades as Record<string, unknown>[] | null
    if (!grade?.length) return NextResponse.json({ error: 'Not graded yet' }, { status: 404 })
    return NextResponse.json(grade[0])
  }

  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { data, error } = await supabaseAdmin
    .from('sessions')
    .select('events, manifest, interviews!inner(hm_id)')
    .eq('id', cid)
    .eq('code', code)
    .eq('interviews.hm_id', hmId)
    .single()

  if (error || !data) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  if (action === 'events.jsonl') {
    const lines = ((data.events as unknown[]) ?? []).map(e => JSON.stringify(e)).join('\n')
    return new NextResponse(lines, { headers: { 'content-type': 'text/plain' } })
  }

  if (action === 'manifest.json') {
    return NextResponse.json(data.manifest)
  }

  return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 404 })
}

export async function POST(req: NextRequest, { params }: Params) {
  const { code, cid, action } = await params
  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  // Verify this session belongs to the HM
  const { data: session } = await supabaseAdmin
    .from('sessions')
    .select('id, interviews!inner(hm_id)')
    .eq('id', cid)
    .eq('code', code)
    .eq('interviews.hm_id', hmId)
    .single()

  if (!session) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  const body = await req.json()

  if (action === 'grade') {
    const { error } = await supabaseAdmin
      .from('grades')
      .upsert({
        session_id:       cid,
        overall_score:    body.overall_score,
        raw_score:        body.raw_score ?? body.overall_score,
        overtime_penalty: body.overtime_penalty ?? null,
        dimensions:       body.dimensions,
        summary:          body.summary,
        standout_moments: body.standout_moments ?? [],
        concerns:         body.concerns ?? [],
        model:            body.model ?? 'local',
        graded_at:        new Date().toISOString(),
      }, { onConflict: 'session_id' })

    if (error) return NextResponse.json({ error: error.message }, { status: 500 })
    return NextResponse.json({ ok: true })
  }

  return NextResponse.json({ error: `Unknown action: ${action}` }, { status: 404 })
}

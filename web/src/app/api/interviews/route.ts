// GET  /api/interviews  — list HM's interviews (auth required)
// POST /api/interviews  — create interview (auth required)

import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { supabaseAdmin } from '@/lib/supabase'
import { generateInterviewCode } from '@/lib/codes'
import { getHmId, ensureProfile } from '@/lib/hmAuth'

export async function GET(req: NextRequest) {
  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { data, error } = await supabaseAdmin
    .from('interviews')
    .select(`id, code, problem, time_limit_minutes, created_at, retired_at, sessions(count)`)
    .eq('hm_id', hmId)
    .order('created_at', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json(data)
}

export async function POST(req: NextRequest) {
  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const body = await req.json()
  const { problem, rubric, time_limit_minutes, reviewer_github_usernames } = body

  if (!problem || !rubric) {
    return NextResponse.json({ error: 'problem and rubric are required' }, { status: 400 })
  }

  // Generate unique code with retry
  let code = ''
  for (let i = 0; i < 5; i++) {
    const candidate = generateInterviewCode()
    const { data: exists } = await supabaseAdmin
      .from('interviews')
      .select('id')
      .eq('code', candidate)
      .single()
    if (!exists) { code = candidate; break }
  }
  if (!code) return NextResponse.json({ error: 'Could not generate unique code' }, { status: 500 })

  const { data, error } = await supabaseAdmin
    .from('interviews')
    .insert({
      hm_id:                       hmId,
      code,
      problem,
      rubric,
      time_limit_minutes:          time_limit_minutes ?? null,
      reviewer_github_usernames:   reviewer_github_usernames ?? [],
    })
    .select('code')
    .single()

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json({ code: data.code })
}

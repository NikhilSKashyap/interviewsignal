// GET  /api/votes/[problem] — get vote count (open)
// POST /api/votes/[problem] — cast vote (open, deduped by IP)

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'

type Params = { params: Promise<{ problem: string }> }

export async function GET(_req: NextRequest, { params }: Params) {
  const { problem } = await params
  const path = decodeURIComponent(problem)

  const { count, error } = await supabaseAdmin
    .from('problem_votes')
    .select('*', { count: 'exact', head: true })
    .eq('problem_path', path)

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json({ problem: path, votes: count ?? 0 })
}

export async function POST(req: NextRequest, { params }: Params) {
  const { problem } = await params
  const path = decodeURIComponent(problem)

  const ip =
    req.headers.get('x-forwarded-for')?.split(',')[0].trim() ??
    req.headers.get('x-real-ip') ??
    'unknown'

  const { error } = await supabaseAdmin
    .from('problem_votes')
    .insert({ problem_path: path, voter_ip: ip })

  // 23505 = unique_violation — already voted, treat as success
  if (error && error.code !== '23505') {
    return NextResponse.json({ error: error.message }, { status: 500 })
  }

  const { count } = await supabaseAdmin
    .from('problem_votes')
    .select('*', { count: 'exact', head: true })
    .eq('problem_path', path)

  return NextResponse.json({ ok: true, votes: count ?? 0 })
}

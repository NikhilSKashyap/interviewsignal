// GET /api/interviews/[code]
// Alias for /api/assignments/[code] — supports the existing Python relay client
// which calls /interviews/<code> not /assignments/<code>.

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ code: string }> }
) {
  const { code } = await params

  const { data, error } = await supabaseAdmin
    .from('interviews')
    .select('code, problem, time_limit_minutes, reviewer_github_usernames')
    .eq('code', code)
    .is('retired_at', null)
    .single()

  if (error || !data) {
    return NextResponse.json({ error: 'Interview not found or expired' }, { status: 404 })
  }

  return NextResponse.json({
    code:                       data.code,
    problem:                    data.problem,
    time_limit_minutes:         data.time_limit_minutes,
    reviewer_github_usernames:  data.reviewer_github_usernames ?? [],
    relay_url:                  'https://tryinterviewsignal.vercel.app/api',
  })
}

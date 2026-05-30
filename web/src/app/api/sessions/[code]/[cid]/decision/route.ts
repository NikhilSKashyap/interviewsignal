// POST /api/sessions/[code]/[cid]/decision

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'
import { getHmId } from '@/lib/hmAuth'

type Params = { params: Promise<{ code: string; cid: string }> }

export async function POST(req: NextRequest, { params }: Params) {
  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { cid } = await params
  const { decision } = await req.json()

  if (!['yes', 'no', 'maybe'].includes(decision)) {
    return NextResponse.json({ error: 'Invalid decision' }, { status: 400 })
  }

  const { error } = await supabaseAdmin
    .from('sessions')
    .update({ decision })
    .eq('id', cid)

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ ok: true })
}

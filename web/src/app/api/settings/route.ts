// GET  /api/settings — return HM settings
// POST /api/settings — update HM settings

import { NextRequest, NextResponse } from 'next/server'
import { supabaseAdmin } from '@/lib/supabase'
import { getHmId, ensureProfile } from '@/lib/hmAuth'
import { auth } from '@clerk/nextjs/server'

export async function GET(req: NextRequest) {
  const hmId = await getHmId(req)
  if (!hmId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { data } = await supabaseAdmin
    .from('hm_profiles')
    .select('custom_relay_url, custom_relay_hm_key, claude_api_key, hm_key')
    .eq('id', hmId)
    .single()

  return NextResponse.json({
    custom_relay_url:    data?.custom_relay_url    ?? null,
    custom_relay_hm_key: data?.custom_relay_hm_key ?? null,
    has_claude_api_key:  !!data?.claude_api_key,
    hm_key:              data?.hm_key              ?? null,
  })
}

export async function POST(req: NextRequest) {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  await ensureProfile(userId)
  const body = await req.json()

  const updates: Record<string, unknown> = {}
  if ('custom_relay_url'    in body) updates.custom_relay_url    = body.custom_relay_url    || null
  if ('custom_relay_hm_key' in body) updates.custom_relay_hm_key = body.custom_relay_hm_key || null
  if ('claude_api_key'      in body) updates.claude_api_key      = body.claude_api_key      || null

  const { error } = await supabaseAdmin
    .from('hm_profiles')
    .update(updates)
    .eq('clerk_id', userId)

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })
  return NextResponse.json({ ok: true })
}

// POST /api/register
// Returns the HM's hm_key. Requires Clerk auth.
// Called by `interview configure-relay` to get the key for local dashboard use.

import { NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { supabaseAdmin } from '@/lib/supabase'
import { ensureProfile, getHmKey } from '@/lib/hmAuth'

export async function POST() {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Sign in at tryinterviewsignal.vercel.app first' }, { status: 401 })

  await ensureProfile(userId)
  const hm_key = await getHmKey(userId)
  if (!hm_key) return NextResponse.json({ error: 'Could not generate key' }, { status: 500 })

  return NextResponse.json({ hm_key })
}

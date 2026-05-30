// GET /api/me — returns the HM's hm_key for local dashboard config
import { NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { ensureProfile, getHmKey } from '@/lib/hmAuth'

export async function GET() {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  await ensureProfile(userId)
  const hm_key = await getHmKey(userId)

  return NextResponse.json({ hm_key })
}

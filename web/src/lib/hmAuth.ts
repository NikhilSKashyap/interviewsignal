// Shared HM authentication helper.
// Accepts either a Clerk JWT (web dashboard) or hm_key Bearer token (local dashboard).

import { auth, currentUser } from '@clerk/nextjs/server'
import { supabaseAdmin } from '@/lib/supabase'
import { NextRequest } from 'next/server'
import { randomUUID } from 'crypto'

export async function getHmId(req: NextRequest): Promise<string | null> {
  // 1. Try hm_key Bearer token (local dashboard)
  const authHeader = req.headers.get('authorization') ?? ''
  if (authHeader.startsWith('Bearer ')) {
    const key = authHeader.slice(7).trim()
    if (key) {
      const { data } = await supabaseAdmin
        .from('hm_profiles')
        .select('id')
        .eq('hm_key', key)
        .single()
      if (data) return data.id
    }
  }

  // 2. Try Clerk JWT (web dashboard)
  try {
    const { userId } = await auth()
    if (userId) return await ensureProfile(userId)
  } catch { /* not a Clerk request */ }

  return null
}

export async function ensureProfile(userId: string): Promise<string | null> {
  const { data: existing } = await supabaseAdmin
    .from('hm_profiles')
    .select('id, hm_key')
    .eq('clerk_id', userId)
    .single()

  if (existing) {
    // Backfill hm_key if missing
    if (!existing.hm_key) {
      await supabaseAdmin
        .from('hm_profiles')
        .update({ hm_key: `is_${randomUUID().replace(/-/g, '')}` })
        .eq('id', existing.id)
    }
    return existing.id
  }

  const user = await currentUser()
  const github = user?.externalAccounts?.find(a => a.provider === 'github')

  const { data: created, error } = await supabaseAdmin
    .from('hm_profiles')
    .insert({
      clerk_id:        userId,
      github_username: github?.username ?? user?.username ?? null,
      github_avatar:   user?.imageUrl   ?? null,
      hm_key:          `is_${randomUUID().replace(/-/g, '')}`,
    })
    .select('id')
    .single()

  if (error) { console.error('ensureProfile:', error); return null }
  return created.id
}

export async function getHmKey(userId: string): Promise<string | null> {
  const { data } = await supabaseAdmin
    .from('hm_profiles')
    .select('hm_key')
    .eq('clerk_id', userId)
    .single()
  return data?.hm_key ?? null
}

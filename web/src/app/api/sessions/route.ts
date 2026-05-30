// GET /api/sessions — HM fetches all their sessions (auth required)

import { NextResponse } from 'next/server'
import { auth, currentUser } from '@clerk/nextjs/server'
import { supabaseAdmin } from '@/lib/supabase'

async function ensureProfile(userId: string): Promise<string | null> {
  const { data: existing } = await supabaseAdmin
    .from('hm_profiles').select('id').eq('clerk_id', userId).single()
  if (existing) return existing.id

  const user = await currentUser()
  const github = user?.externalAccounts?.find(a => a.provider === 'github')
  const { data: created, error } = await supabaseAdmin
    .from('hm_profiles')
    .insert({ clerk_id: userId, github_username: github?.username ?? null, github_avatar: user?.imageUrl ?? null })
    .select('id').single()
  if (error) return null
  return created.id
}

export async function GET() {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const hmId = await ensureProfile(userId)
  if (!hmId) return NextResponse.json({ error: 'Could not load profile' }, { status: 500 })

  const hm = { id: hmId }

  const { data, error } = await supabaseAdmin
    .from('sessions')
    .select(`
      id, code, candidate_name, candidate_email, github_username,
      github_avatar, github_repo_url, elapsed_minutes, sealed,
      final_hash, created_at,
      grades(overall_score, raw_score, overtime_penalty, summary, graded_at),
      interviews!inner(hm_id)
    `)
    .eq('interviews.hm_id', hm.id)
    .order('created_at', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json(data)
}

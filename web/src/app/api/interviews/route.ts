// GET  /api/interviews  — list HM's interviews (auth required)
// POST /api/interviews  — create interview (auth required)

import { NextRequest, NextResponse } from 'next/server'
import { auth, currentUser } from '@clerk/nextjs/server'
import { supabaseAdmin } from '@/lib/supabase'
import { generateInterviewCode } from '@/lib/codes'

// Upsert HM profile — called before any HM action so profile always exists
async function ensureProfile(userId: string): Promise<string | null> {
  // Try to find existing profile first
  const { data: existing } = await supabaseAdmin
    .from('hm_profiles')
    .select('id')
    .eq('clerk_id', userId)
    .single()

  if (existing) return existing.id

  // Create it from Clerk user data
  const user = await currentUser()
  const github = user?.externalAccounts?.find(a => a.provider === 'github')

  const { data: created, error } = await supabaseAdmin
    .from('hm_profiles')
    .insert({
      clerk_id:        userId,
      github_username: github?.username ?? user?.username ?? null,
      github_avatar:   user?.imageUrl ?? null,
    })
    .select('id')
    .single()

  if (error) {
    console.error('ensureProfile error:', error)
    return null
  }

  return created.id
}

export async function GET() {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const hmId = await ensureProfile(userId)
  if (!hmId) return NextResponse.json({ error: 'Could not load profile' }, { status: 500 })

  const { data, error } = await supabaseAdmin
    .from('interviews')
    .select(`id, code, problem, time_limit_minutes, created_at, retired_at, sessions(count)`)
    .eq('hm_id', hmId)
    .order('created_at', { ascending: false })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json(data)
}

export async function POST(req: NextRequest) {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const body = await req.json()
  const { problem, rubric, time_limit_minutes, reviewer_github_usernames } = body

  if (!problem || !rubric) {
    return NextResponse.json({ error: 'problem and rubric are required' }, { status: 400 })
  }

  const hmId = await ensureProfile(userId)
  if (!hmId) return NextResponse.json({ error: 'Could not load profile' }, { status: 500 })

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

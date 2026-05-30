// POST /api/user/sync
// Called after sign-in to create hm_profiles row if it doesn't exist.

import { NextResponse } from 'next/server'
import { auth, currentUser } from '@clerk/nextjs/server'
import { supabaseAdmin } from '@/lib/supabase'

export async function POST() {
  const { userId } = await auth()
  if (!userId) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const user = await currentUser()
  const github = user?.externalAccounts?.find(a => a.provider === 'github')

  const { error } = await supabaseAdmin
    .from('hm_profiles')
    .upsert({
      clerk_id:        userId,
      github_username: github?.username        ?? user?.username ?? null,
      github_avatar:   user?.imageUrl          ?? null,
    }, {
      onConflict: 'clerk_id',
      ignoreDuplicates: false,
    })

  if (error) return NextResponse.json({ error: error.message }, { status: 500 })

  return NextResponse.json({ ok: true })
}

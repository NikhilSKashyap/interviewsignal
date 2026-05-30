import { createClient } from '@supabase/supabase-js'

const supabaseUrl  = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
const supabaseService = process.env.SUPABASE_SERVICE_KEY!

// Client-side — respects RLS
export const supabase = createClient(supabaseUrl, supabaseAnon)

// Server-side only — bypasses RLS (use only in API routes)
export const supabaseAdmin = createClient(supabaseUrl, supabaseService)

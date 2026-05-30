/**
 * relayProxy.ts
 * Routes dashboard reads/writes to Supabase (community) or a custom relay (power users).
 *
 * Community relay: no custom_relay_url set → use Supabase directly.
 * Custom relay:    custom_relay_url set     → HTTP proxy with hm_key Bearer auth.
 *
 * Grading only works for community relay (rubric lives in Supabase).
 * Power users grade via their local Python dashboard.
 */

import { supabaseAdmin } from '@/lib/supabase'

// ─── Types ────────────────────────────────────────────────────────────────────

export type SessionSummary = {
  id:              string
  code:            string
  candidate_name:  string | null
  candidate_email: string | null
  github_username: string | null
  github_avatar:   string | null
  github_repo_url: string | null
  elapsed_minutes: number | null
  final_hash:      string | null
  created_at:      string
  decision:        string | null
  grade:           { overall_score: number; raw_score: number; summary: string; overtime_penalty: unknown } | null
}

export type SessionDetail = SessionSummary & {
  events:     unknown[]
  manifest:   Record<string, unknown>
  git_diff:   string | null
  commit_log: unknown[]
  rubric:     string | null   // only available for community relay
  problem:    string | null
  time_limit_minutes: number | null
}

export type HmProfile = {
  id:                  string
  custom_relay_url:    string | null
  custom_relay_hm_key: string | null
  claude_api_key:      string | null
}

// ─── Load HM profile ──────────────────────────────────────────────────────────

export async function loadHmProfile(hmId: string): Promise<HmProfile | null> {
  const { data } = await supabaseAdmin
    .from('hm_profiles')
    .select('id, custom_relay_url, custom_relay_hm_key, claude_api_key')
    .eq('id', hmId)
    .single()
  return data as HmProfile | null
}

// ─── Proxy factory ────────────────────────────────────────────────────────────

export function getProxy(profile: HmProfile) {
  if (profile.custom_relay_url) {
    return new CustomRelayProxy(profile)
  }
  return new SupabaseProxy(profile.id)
}

// ─── Supabase proxy (community relay) ────────────────────────────────────────

class SupabaseProxy {
  constructor(private hmId: string) {}

  async listSessions(): Promise<SessionSummary[]> {
    const { data, error } = await supabaseAdmin
      .from('sessions')
      .select(`
        id, code, candidate_name, candidate_email, github_username,
        github_avatar, github_repo_url, elapsed_minutes, final_hash,
        created_at, decision,
        grades(overall_score, raw_score, summary, overtime_penalty),
        interviews!inner(hm_id)
      `)
      .eq('interviews.hm_id', this.hmId)
      .order('created_at', { ascending: false })

    if (error) return []
    return (data ?? []).map(s => {
      const g = (s as Record<string, unknown>).grades as Record<string, unknown>[]
      return {
        id:              s.id,
        code:            s.code,
        candidate_name:  s.candidate_name,
        candidate_email: s.candidate_email,
        github_username: s.github_username,
        github_avatar:   s.github_avatar,
        github_repo_url: s.github_repo_url,
        elapsed_minutes: s.elapsed_minutes,
        final_hash:      s.final_hash,
        created_at:      s.created_at,
        decision:        s.decision ?? null,
        grade:           g?.[0] ? { overall_score: g[0].overall_score as number, raw_score: g[0].raw_score as number, summary: g[0].summary as string, overtime_penalty: g[0].overtime_penalty } : null,
      }
    })
  }

  async getSessionDetail(sessionId: string): Promise<SessionDetail | null> {
    const { data, error } = await supabaseAdmin
      .from('sessions')
      .select(`
        id, code, candidate_name, candidate_email, github_username,
        github_avatar, github_repo_url, elapsed_minutes, final_hash,
        created_at, decision, events, manifest, git_diff, commit_log,
        grades(overall_score, raw_score, summary, overtime_penalty, dimensions, standout_moments, concerns, graded_at),
        interviews!inner(hm_id, rubric, problem, time_limit_minutes)
      `)
      .eq('id', sessionId)
      .eq('interviews.hm_id', this.hmId)
      .single()

    if (error || !data) return null
    const iv = (data as Record<string, unknown>).interviews as Record<string, unknown>
    const g  = (data as Record<string, unknown>).grades as Record<string, unknown>[]
    return {
      id:              data.id,
      code:            data.code,
      candidate_name:  data.candidate_name,
      candidate_email: data.candidate_email,
      github_username: data.github_username,
      github_avatar:   data.github_avatar,
      github_repo_url: data.github_repo_url,
      elapsed_minutes: data.elapsed_minutes,
      final_hash:      data.final_hash,
      created_at:      data.created_at,
      decision:        data.decision ?? null,
      events:          (data.events as unknown[]) ?? [],
      manifest:        (data.manifest as Record<string, unknown>) ?? {},
      git_diff:        data.git_diff,
      commit_log:      (data.commit_log as unknown[]) ?? [],
      rubric:          iv?.rubric as string ?? null,
      problem:         iv?.problem as string ?? null,
      time_limit_minutes: iv?.time_limit_minutes as number ?? null,
      grade:           g?.[0] ? { overall_score: g[0].overall_score as number, raw_score: g[0].raw_score as number, summary: g[0].summary as string, overtime_penalty: g[0].overtime_penalty } : null,
    }
  }

  async saveGrade(sessionId: string, grade: Record<string, unknown>): Promise<void> {
    await supabaseAdmin.from('grades').upsert(
      { session_id: sessionId, ...grade, graded_at: new Date().toISOString() },
      { onConflict: 'session_id' }
    )
  }

  async saveDecision(sessionId: string, decision: string): Promise<void> {
    await supabaseAdmin.from('sessions').update({ decision }).eq('id', sessionId)
  }

  isCustomRelay() { return false }
}

// ─── Custom relay proxy (power users) ────────────────────────────────────────

class CustomRelayProxy {
  private relayUrl: string
  private hmKey: string

  constructor(profile: HmProfile) {
    this.relayUrl = profile.custom_relay_url!.replace(/\/$/, '')
    this.hmKey    = profile.custom_relay_hm_key ?? ''
  }

  private async _fetch(path: string, method = 'GET', body?: unknown) {
    const res = await fetch(`${this.relayUrl}${path}`, {
      method,
      headers: {
        'Authorization': `Bearer ${this.hmKey}`,
        'Content-Type':  'application/json',
      },
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) throw new Error(`Relay ${method} ${path} → ${res.status}`)
    return res.json()
  }

  async listSessions(): Promise<SessionSummary[]> {
    try {
      const data = await this._fetch('/sessions')
      const flat: SessionSummary[] = []
      for (const iv of data?.interviews ?? []) {
        for (const c of iv.candidates ?? []) {
          flat.push({
            id:              c.cid,
            code:            iv.code,
            candidate_name:  c.name ?? null,
            candidate_email: c.email ?? null,
            github_username: c.github_username ?? null,
            github_avatar:   null,
            github_repo_url: c.github_repo_url ?? null,
            elapsed_minutes: c.elapsed_minutes ?? null,
            final_hash:      c.final_hash ?? null,
            created_at:      c.submitted_at ? new Date(c.submitted_at * 1000).toISOString() : '',
            decision:        c.decision ?? null,
            grade:           c.overall_score != null ? { overall_score: c.overall_score, raw_score: c.overall_score, summary: '', overtime_penalty: null } : null,
          })
        }
      }
      return flat
    } catch { return [] }
  }

  async getSessionDetail(sessionId: string, code?: string): Promise<SessionDetail | null> {
    try {
      const path = code ? `/sessions/${code}/${sessionId}` : `/sessions/${sessionId}`
      const data  = await this._fetch(path)
      const evPath = code ? `/sessions/${code}/${sessionId}/events.jsonl` : null
      let events: unknown[] = []
      if (evPath) {
        const raw = await fetch(`${this.relayUrl}${evPath}`, {
          headers: { 'Authorization': `Bearer ${this.hmKey}` }
        }).then(r => r.text())
        events = raw.trim().split('\n').filter(Boolean).map(l => JSON.parse(l))
      }
      return { ...data, events, rubric: null, grade: null }
    } catch { return null }
  }

  async saveGrade(sessionId: string, grade: Record<string, unknown>, code?: string): Promise<void> {
    const path = code ? `/sessions/${code}/${sessionId}/grade` : `/sessions/${sessionId}/grade`
    await this._fetch(path, 'POST', grade)
  }

  async saveDecision(sessionId: string, decision: string, code?: string): Promise<void> {
    const path = code ? `/sessions/${code}/${sessionId}/decision` : `/sessions/${sessionId}/decision`
    await this._fetch(path, 'POST', { decision })
  }

  isCustomRelay() { return true }
}

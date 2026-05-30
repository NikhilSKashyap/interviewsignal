'use client'

import { useState, useEffect } from 'react'
import { computeFlags, type Flag } from '@/lib/flagsComputer'
import { buildTranscript } from '@/lib/transcriptBuilder'

// ─── Types ────────────────────────────────────────────────────────────────────

type Grade = {
  overall_score:    number
  raw_score:        number
  summary:          string
  overtime_penalty: { penalty: number; overtime_minutes: number } | null
  dimensions?:      { name: string; score: number; justification: string }[]
  standout_moments?: string[]
  concerns?:        string[]
}

type Session = {
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
  grade:           Grade | null
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function ScoreBadge({ score }: { score: number }) {
  const color = score >= 7.5 ? 'bg-emerald-900/50 text-emerald-300 border-emerald-700'
              : score >= 5   ? 'bg-yellow-900/50 text-yellow-300 border-yellow-700'
                             : 'bg-red-900/50 text-red-300 border-red-700'
  return (
    <span className={`inline-flex items-center rounded-lg border px-2.5 py-1 text-sm font-semibold ${color}`}>
      {score.toFixed(1)}
    </span>
  )
}

function FlagPill({ flag }: { flag: Flag }) {
  return (
    <div className={`rounded-lg border p-3 ${flag.severity === 'red' ? 'border-red-800 bg-red-900/20' : 'border-yellow-800 bg-yellow-900/20'}`}>
      <p className={`text-xs font-semibold ${flag.severity === 'red' ? 'text-red-400' : 'text-yellow-400'}`}>
        {flag.severity === 'red' ? '🔴' : '🟡'} {flag.label}
      </p>
      <p className="mt-0.5 text-xs text-zinc-400">{flag.detail}</p>
    </div>
  )
}

// ─── Drawer ───────────────────────────────────────────────────────────────────

export function SessionDrawer({
  session,
  onClose,
  onDecision,
  onGraded,
}: {
  session:    Session
  onClose:    () => void
  onDecision: (id: string, decision: string) => void
  onGraded:   (id: string, grade: Grade) => void
}) {
  const [tab, setTab]         = useState<'overview' | 'transcript' | 'flags'>('overview')
  const [detail, setDetail]   = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(false)
  const [grading, setGrading] = useState(false)
  const [gradeErr, setGradeErr] = useState('')
  const [deciding, setDeciding] = useState<string | null>(null)
  const [grade, setGrade]     = useState<Grade | null>(session.grade)
  const [decision, setDecision] = useState(session.decision)

  // Load detail when transcript or flags tab is opened
  useEffect(() => {
    if ((tab === 'transcript' || tab === 'flags') && !detail) {
      setLoading(true)
      fetch(`/api/sessions/${session.code}/${session.id}`)
        .then(r => r.json())
        .then(d => { setDetail(d); setLoading(false) })
        .catch(() => setLoading(false))
    }
  }, [tab, detail, session.code, session.id])

  async function handleGrade() {
    setGrading(true)
    setGradeErr('')
    const res  = await fetch('/api/grade', {
      method:  'POST',
      headers: { 'content-type': 'application/json' },
      body:    JSON.stringify({ session_id: session.id }),
    })
    const data = await res.json()
    setGrading(false)
    if (!res.ok) { setGradeErr(data.error ?? 'Grading failed'); return }
    setGrade(data.grade)
    onGraded(session.id, data.grade)
  }

  async function handleDecision(d: string) {
    setDeciding(d)
    await fetch(`/api/sessions/${session.code}/${session.id}/decision`, {
      method:  'POST',
      headers: { 'content-type': 'application/json' },
      body:    JSON.stringify({ decision: d }),
    })
    setDecision(d)
    setDeciding(null)
    onDecision(session.id, d)
  }

  const events    = (detail?.events  as Record<string, unknown>[]) ?? []
  const manifest  = (detail?.manifest as Record<string, unknown>) ?? {}
  const flags     = detail ? computeFlags(events, { ...manifest, elapsed_minutes: session.elapsed_minutes ?? 0, time_limit_minutes: detail.time_limit_minutes as number }) : []
  const transcript = detail ? buildTranscript(events as Parameters<typeof buildTranscript>[0]) : ''

  const decisionStyle = (d: string) => {
    if (decision === d) {
      if (d === 'yes')   return 'border-emerald-600 bg-emerald-900/40 text-emerald-300'
      if (d === 'no')    return 'border-red-600 bg-red-900/40 text-red-300'
      return 'border-yellow-600 bg-yellow-900/40 text-yellow-300'
    }
    return 'border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-white'
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="flex h-full w-full max-w-2xl flex-col border-l border-zinc-700 bg-zinc-900 shadow-2xl">

        {/* Header */}
        <div className="flex items-start justify-between border-b border-zinc-800 px-6 py-4 shrink-0">
          <div className="flex items-center gap-3">
            {session.github_avatar && (
              <img src={session.github_avatar} alt="" className="h-10 w-10 rounded-full" />
            )}
            <div>
              <p className="font-semibold text-white">
                {session.candidate_name ?? session.github_username ?? session.candidate_email ?? 'Anonymous'}
              </p>
              <div className="flex items-center gap-2 mt-0.5">
                {session.candidate_email && <p className="text-xs text-zinc-400">{session.candidate_email}</p>}
                <span className="font-mono text-xs text-zinc-600">{session.code}</span>
              </div>
            </div>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-white mt-1">✕</button>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-zinc-800 px-6 py-2 shrink-0">
          {(['overview', 'transcript', 'flags'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative rounded-md px-3 py-1.5 text-xs font-medium transition-colors capitalize ${tab === t ? 'bg-zinc-800 text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
            >
              {t}
              {t === 'flags' && flags.length > 0 && detail && (
                <span className={`ml-1 rounded-full px-1.5 py-0.5 text-xs font-bold ${flags.some(f => f.severity === 'red') ? 'bg-red-800 text-red-200' : 'bg-yellow-800 text-yellow-200'}`}>
                  {flags.length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">

          {/* Overview tab */}
          {tab === 'overview' && (
            <div className="space-y-5">
              {/* Stats */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border border-zinc-800 bg-zinc-800/50 p-3">
                  <p className="text-xs text-zinc-500">Duration</p>
                  <p className="mt-1 font-medium text-white">{session.elapsed_minutes != null ? `${session.elapsed_minutes.toFixed(0)}m` : '—'}</p>
                </div>
                {session.github_repo_url && (
                  <a href={session.github_repo_url} target="_blank" rel="noopener noreferrer"
                    className="rounded-lg border border-zinc-800 bg-zinc-800/50 p-3 hover:border-zinc-600">
                    <p className="text-xs text-zinc-500">GitHub repo</p>
                    <p className="mt-1 text-sm font-medium text-emerald-400">View →</p>
                  </a>
                )}
                <div className="rounded-lg border border-zinc-800 bg-zinc-800/50 p-3">
                  <p className="text-xs text-zinc-500">Hash</p>
                  <p className="mt-1 font-mono text-xs text-zinc-400 truncate">{session.final_hash?.slice(0, 12) ?? '—'}</p>
                </div>
              </div>

              {/* Decision */}
              <div>
                <p className="mb-2 text-xs font-medium text-zinc-500">Decision</p>
                <div className="flex gap-2">
                  {[['yes', '✓ Advance'], ['maybe', '→ Maybe'], ['no', '✗ Reject']].map(([d, label]) => (
                    <button
                      key={d}
                      onClick={() => handleDecision(d)}
                      disabled={deciding !== null}
                      className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors disabled:opacity-50 ${decisionStyle(d)}`}
                    >
                      {deciding === d ? '…' : label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Grade */}
              {grade ? (
                <div className="rounded-xl border border-zinc-700 bg-zinc-800/50 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <p className="text-sm font-medium text-white">AI Grade</p>
                    <div className="flex items-center gap-2">
                      {grade.overtime_penalty && (
                        <span className="text-xs text-yellow-400">
                          {grade.raw_score.toFixed(1)} −{grade.overtime_penalty.penalty.toFixed(2)} overtime
                        </span>
                      )}
                      <ScoreBadge score={grade.overall_score} />
                    </div>
                  </div>
                  <p className="mb-3 text-sm text-zinc-300">{grade.summary}</p>

                  {grade.dimensions && (
                    <div className="mb-3 space-y-2">
                      {grade.dimensions.map(d => (
                        <div key={d.name} className="flex items-start gap-3">
                          <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${d.score >= 7 ? 'bg-emerald-900/50 text-emerald-300' : d.score >= 5 ? 'bg-yellow-900/50 text-yellow-300' : 'bg-red-900/50 text-red-300'}`}>
                            {d.score}/10
                          </span>
                          <div>
                            <p className="text-xs font-medium text-zinc-300">{d.name}</p>
                            <p className="text-xs text-zinc-500">{d.justification}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {grade.standout_moments?.length ? (
                    <div className="mb-2">
                      <p className="mb-1 text-xs font-medium text-emerald-400">Standout moments</p>
                      {grade.standout_moments.map((m, i) => <p key={i} className="text-xs text-zinc-400">· {m}</p>)}
                    </div>
                  ) : null}

                  {grade.concerns?.length ? (
                    <div>
                      <p className="mb-1 text-xs font-medium text-yellow-400">Concerns</p>
                      {grade.concerns.map((c, i) => <p key={i} className="text-xs text-zinc-400">· {c}</p>)}
                    </div>
                  ) : null}

                  <button onClick={handleGrade} disabled={grading} className="mt-3 text-xs text-zinc-600 hover:text-zinc-400 disabled:opacity-50">
                    {grading ? 'Regrading…' : 'Regrade'}
                  </button>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-zinc-700 p-5 text-center">
                  {gradeErr && <p className="mb-3 text-xs text-red-400">{gradeErr}</p>}
                  <p className="mb-3 text-sm text-zinc-400">Session not graded yet</p>
                  <button
                    onClick={handleGrade}
                    disabled={grading}
                    className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-black hover:bg-zinc-200 disabled:opacity-50"
                  >
                    {grading ? 'Grading…' : 'Grade with Claude'}
                  </button>
                  {grading && <p className="mt-2 text-xs text-zinc-600">This may take up to 30 seconds…</p>}
                </div>
              )}
            </div>
          )}

          {/* Transcript tab */}
          {tab === 'transcript' && (
            loading
              ? <p className="text-sm text-zinc-500">Loading transcript…</p>
              : transcript
                ? <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-zinc-300">{transcript}</pre>
                : <p className="text-sm text-zinc-500">No transcript data</p>
          )}

          {/* Flags tab */}
          {tab === 'flags' && (
            loading
              ? <p className="text-sm text-zinc-500">Loading flags…</p>
              : flags.length === 0
                ? <p className="text-sm text-zinc-500">No flags raised for this session.</p>
                : <div className="space-y-3">{flags.map(f => <FlagPill key={f.id} flag={f} />)}</div>
          )}
        </div>

        <div className="border-t border-zinc-800 px-6 py-3 shrink-0">
          <p className="text-xs text-zinc-600">Submitted {new Date(session.created_at).toLocaleString()}</p>
        </div>
      </div>
    </div>
  )
}

'use client'

import { useEffect, useState } from 'react'
import { useUser } from '@clerk/nextjs'
import { redirect } from 'next/navigation'

type Prefill = { problem: string; rubric: string } | null

// ─── Types ────────────────────────────────────────────────────────────────────

type Interview = {
  id: string
  code: string
  problem: string
  time_limit_minutes: number | null
  created_at: string
  retired_at: string | null
  sessions: { count: number }[]
}

type Session = {
  id: string
  code: string
  candidate_name: string | null
  candidate_email: string | null
  github_username: string | null
  github_avatar: string | null
  github_repo_url: string | null
  elapsed_minutes: number | null
  sealed: boolean
  final_hash: string | null
  created_at: string
  grades: {
    overall_score: number
    raw_score: number
    overtime_penalty: { penalty: number; overtime_minutes: number } | null
    summary: string
    graded_at: string
  }[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${color}`}>
      {text}
    </span>
  )
}

function ScorePill({ session }: { session: Session }) {
  const grade = session.grades?.[0]
  if (!grade) return <Badge text="Ungraded" color="bg-zinc-800 text-zinc-400" />
  const score = grade.overall_score
  const color =
    score >= 7.5 ? 'bg-emerald-900 text-emerald-300' :
    score >= 5   ? 'bg-yellow-900 text-yellow-300' :
                   'bg-red-900 text-red-300'
  return (
    <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${color}`}>
      {score.toFixed(1)}
      {grade.overtime_penalty && (
        <span className="text-zinc-400 ml-1">
          ({grade.raw_score.toFixed(1)} −{grade.overtime_penalty.penalty.toFixed(2)})
        </span>
      )}
    </span>
  )
}

// ─── Create Interview Modal ────────────────────────────────────────────────────

function CreateModal({ onClose, onCreated, prefill }: { onClose: () => void; onCreated: (code: string) => void; prefill?: Prefill }) {
  const [problem, setProblem] = useState(prefill?.problem ?? '')
  const [rubric, setRubric] = useState(prefill?.rubric ?? '')
  const [timeLimit, setTimeLimit] = useState('90')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!problem.trim() || !rubric.trim()) {
      setError('Problem and rubric are required')
      return
    }
    setLoading(true)
    setError('')
    const res = await fetch('/api/interviews', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        problem: problem.trim(),
        rubric: rubric.trim(),
        time_limit_minutes: timeLimit ? parseInt(timeLimit) : null,
      }),
    })
    const data = await res.json()
    setLoading(false)
    if (!res.ok) { setError(data.error ?? 'Failed'); return }
    onCreated(data.code)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-2xl rounded-xl border border-zinc-700 bg-zinc-900 p-6 shadow-2xl">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Create Interview</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white">✕</button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Problem statement</label>
            <textarea
              rows={5}
              placeholder="Describe the problem the candidate will solve..."
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
              value={problem}
              onChange={e => setProblem(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Grading rubric</label>
            <textarea
              rows={5}
              placeholder="Define dimensions and weights, e.g. Problem decomposition (30%), AI collaboration quality (30%), Code correctness (40%)..."
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-none"
              value={rubric}
              onChange={e => setRubric(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Time limit (minutes)</label>
            <input
              type="number"
              className="w-32 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-zinc-500 focus:outline-none"
              value={timeLimit}
              onChange={e => setTimeLimit(e.target.value)}
            />
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={onClose}
              className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={loading}
              className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-black hover:bg-zinc-200 disabled:opacity-50"
            >
              {loading ? 'Creating...' : 'Create interview'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Code Banner ──────────────────────────────────────────────────────────────

function CodeBanner({ code, onClose }: { code: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const installLine = `pip install interviewsignal && interview install && /interview ${code}`

  function copy() {
    navigator.clipboard.writeText(installLine)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-xl rounded-xl border border-emerald-700 bg-zinc-900 p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Interview created</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white">✕</button>
        </div>
        <p className="mb-2 text-sm text-zinc-400">Share this one-liner with your candidates:</p>
        <div className="flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-800 p-3">
          <code className="flex-1 break-all text-sm text-emerald-400">{installLine}</code>
          <button
            onClick={copy}
            className="shrink-0 rounded px-3 py-1 text-xs font-medium bg-zinc-700 text-zinc-200 hover:bg-zinc-600"
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
        <p className="mt-3 text-xs text-zinc-500">
          Code: <span className="font-mono text-white">{code}</span> · candidates submit with <code className="text-zinc-300">/submit</code>
        </p>
      </div>
    </div>
  )
}

// ─── Session Detail Drawer ─────────────────────────────────────────────────────

function SessionDrawer({ session, onClose }: { session: Session; onClose: () => void }) {
  const grade = session.grades?.[0]

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50">
      <div className="flex h-full w-full max-w-2xl flex-col overflow-y-auto border-l border-zinc-700 bg-zinc-900 p-6 shadow-2xl">
        <div className="mb-6 flex items-start justify-between">
          <div>
            <p className="text-xs font-mono text-zinc-500">{session.code}</p>
            <h2 className="mt-1 text-lg font-semibold text-white">
              {session.candidate_name ?? session.github_username ?? session.candidate_email ?? 'Anonymous'}
            </h2>
            {session.candidate_email && (
              <p className="text-sm text-zinc-400">{session.candidate_email}</p>
            )}
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-white">✕</button>
        </div>

        {/* Stats row */}
        <div className="mb-6 flex flex-wrap gap-3">
          <div className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2">
            <p className="text-xs text-zinc-500">Duration</p>
            <p className="text-sm font-medium text-white">
              {session.elapsed_minutes != null ? `${session.elapsed_minutes.toFixed(1)} min` : '—'}
            </p>
          </div>
          {session.github_repo_url && (
            <a
              href={session.github_repo_url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 hover:border-zinc-500"
            >
              <p className="text-xs text-zinc-500">GitHub repo</p>
              <p className="text-sm font-medium text-emerald-400">View →</p>
            </a>
          )}
          <div className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2">
            <p className="text-xs text-zinc-500">Final hash</p>
            <p className="text-xs font-mono text-zinc-400">{session.final_hash ?? '—'}</p>
          </div>
        </div>

        {/* Grade */}
        {grade ? (
          <div className="mb-6 rounded-xl border border-zinc-700 bg-zinc-800 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-medium text-white">AI Grade</h3>
              <ScorePill session={session} />
            </div>
            <p className="text-sm text-zinc-300">{grade.summary}</p>
            {grade.overtime_penalty && (
              <p className="mt-2 text-xs text-yellow-400">
                ⚠ Submitted {grade.overtime_penalty.overtime_minutes} min over limit — penalty applied
              </p>
            )}
          </div>
        ) : (
          <div className="mb-6 rounded-xl border border-dashed border-zinc-700 p-4 text-center text-sm text-zinc-500">
            Not graded yet — use your local dashboard to grade
          </div>
        )}

        <p className="text-xs text-zinc-600 mt-auto">
          Submitted {new Date(session.created_at).toLocaleString()}
        </p>
      </div>
    </div>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { isLoaded, isSignedIn } = useUser()

  const [interviews, setInterviews] = useState<Interview[]>([])
  const [sessions, setSessions]     = useState<Session[]>([])
  const [loading, setLoading]       = useState(true)
  const [activeCode, setActiveCode] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [createPrefill, setCreatePrefill] = useState<Prefill>(null)
  const [newCode, setNewCode]       = useState<string | null>(null)
  const [selected, setSelected]     = useState<Session | null>(null)

  useEffect(() => {
    if (!isLoaded) return
    if (!isSignedIn) { redirect('/sign-in'); return }

    async function load() {
      // Check for prefill from problems library
      const raw = sessionStorage.getItem('is_prefill')
      if (raw) {
        sessionStorage.removeItem('is_prefill')
        try {
          setCreatePrefill(JSON.parse(raw))
          setShowCreate(true)
        } catch { /* ignore */ }
      }

      // Sync profile on every dashboard load
      await fetch('/api/user/sync', { method: 'POST' })

      const [ivRes, sRes] = await Promise.all([
        fetch('/api/interviews'),
        fetch('/api/sessions'),
      ])
      const [ivData, sData] = await Promise.all([ivRes.json(), sRes.json()])
      setInterviews(Array.isArray(ivData) ? ivData : [])
      setSessions(Array.isArray(sData) ? sData : [])
      setLoading(false)
    }
    load()
  }, [isLoaded, isSignedIn])

  if (!isLoaded || loading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-zinc-950 text-zinc-500 text-sm">
        Loading...
      </div>
    )
  }

  const displaySessions = activeCode
    ? sessions.filter(s => s.code === activeCode)
    : sessions

  return (
    <div className="flex flex-1 bg-zinc-950 text-white">

      {/* Sidebar — interviews */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-zinc-800 lg:flex">
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <span className="text-sm font-semibold text-zinc-300">Interviews</span>
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-md bg-white px-2 py-1 text-xs font-medium text-black hover:bg-zinc-200"
          >
            + New
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          <button
            onClick={() => setActiveCode(null)}
            className={`w-full px-4 py-2 text-left text-sm ${!activeCode ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-white'}`}
          >
            All submissions
            <span className="ml-2 text-xs text-zinc-600">{sessions.length}</span>
          </button>
          {interviews.map(iv => (
            <button
              key={iv.id}
              onClick={() => setActiveCode(iv.code)}
              className={`w-full px-4 py-2 text-left text-sm ${activeCode === iv.code ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-white'}`}
            >
              <span className="block font-mono text-xs text-zinc-500">{iv.code}</span>
              <span className="block truncate">{iv.problem.slice(0, 40)}…</span>
              <span className="text-xs text-zinc-600">
                {iv.sessions?.[0]?.count ?? 0} submissions
                {iv.time_limit_minutes ? ` · ${iv.time_limit_minutes}min` : ''}
              </span>
            </button>
          ))}
        </nav>
      </aside>

      {/* Main — sessions */}
      <main className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
          <h1 className="text-sm font-semibold text-zinc-300">
            {activeCode ? `${activeCode} — submissions` : 'All submissions'}
            <span className="ml-2 text-xs font-normal text-zinc-600">{displaySessions.length}</span>
          </h1>
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-md bg-white px-3 py-1.5 text-xs font-medium text-black hover:bg-zinc-200 lg:hidden"
          >
            + New interview
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {displaySessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-center text-zinc-600 text-sm">
              <p className="text-lg mb-2">No submissions yet</p>
              {activeCode ? (
                <>
                  <p className="mb-4">Share this with candidates:</p>
                  <code className="rounded bg-zinc-800 px-3 py-1.5 text-xs text-emerald-400">
                    pip install interviewsignal &amp;&amp; interview install &amp;&amp; /interview {activeCode}
                  </code>
                </>
              ) : (
                <button
                  onClick={() => setShowCreate(true)}
                  className="mt-4 rounded-lg border border-zinc-700 px-4 py-2 text-zinc-400 hover:border-zinc-500 hover:text-white"
                >
                  Create your first interview →
                </button>
              )}
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-xs text-zinc-500">
                  <th className="px-6 py-3 text-left font-medium">Candidate</th>
                  <th className="px-6 py-3 text-left font-medium">Code</th>
                  <th className="px-6 py-3 text-left font-medium">Duration</th>
                  <th className="px-6 py-3 text-left font-medium">Score</th>
                  <th className="px-6 py-3 text-left font-medium">Submitted</th>
                </tr>
              </thead>
              <tbody>
                {displaySessions.map(s => (
                  <tr
                    key={s.id}
                    onClick={() => setSelected(s)}
                    className="cursor-pointer border-b border-zinc-800/50 hover:bg-zinc-800/40"
                  >
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2">
                        {s.github_avatar && (
                          <img src={s.github_avatar} alt="" className="h-6 w-6 rounded-full" />
                        )}
                        <div>
                          <p className="font-medium text-white">
                            {s.candidate_name ?? s.github_username ?? '—'}
                          </p>
                          {s.candidate_email && (
                            <p className="text-xs text-zinc-500">{s.candidate_email}</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-3">
                      <span className="font-mono text-xs text-zinc-400">{s.code}</span>
                    </td>
                    <td className="px-6 py-3 text-zinc-400">
                      {s.elapsed_minutes != null ? `${s.elapsed_minutes.toFixed(0)}m` : '—'}
                    </td>
                    <td className="px-6 py-3">
                      <ScorePill session={s} />
                    </td>
                    <td className="px-6 py-3 text-zinc-500 text-xs">
                      {new Date(s.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {/* Modals */}
      {showCreate && (
        <CreateModal
          prefill={createPrefill}
          onClose={() => { setShowCreate(false); setCreatePrefill(null) }}
          onCreated={code => {
            setShowCreate(false)
            setNewCode(code)
            fetch('/api/interviews').then(r => r.json()).then(d => setInterviews(Array.isArray(d) ? d : []))
          }}
        />
      )}
      {newCode && (
        <CodeBanner code={newCode} onClose={() => setNewCode(null)} />
      )}
      {selected && (
        <SessionDrawer session={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

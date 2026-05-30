'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useUser } from '@clerk/nextjs'
import ReactMarkdown from 'react-markdown'
import { problems, categories, allTags, type Problem } from '@/data/problems'

// ─── Colours ──────────────────────────────────────────────────────────────────

const catColor: Record<string, string> = {
  backend:  'bg-blue-900/40 text-blue-400 border-blue-800',
  mle:      'bg-purple-900/40 text-purple-400 border-purple-800',
  frontend: 'bg-orange-900/40 text-orange-400 border-orange-800',
}

// ─── Upvote hook ──────────────────────────────────────────────────────────────

function useVotes(slugs: string[]) {
  const [counts, setCounts] = useState<Record<string, number>>({})

  useEffect(() => {
    Promise.all(
      slugs.map(s =>
        fetch(`/api/votes/${encodeURIComponent(s)}`)
          .then(r => r.json())
          .then(d => [s, d.votes ?? 0] as [string, number])
          .catch(() => [s, 0] as [string, number])
      )
    ).then(entries => setCounts(Object.fromEntries(entries)))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function vote(slug: string) {
    const res  = await fetch(`/api/votes/${encodeURIComponent(slug)}`, { method: 'POST' })
    const data = await res.json()
    setCounts(prev => ({ ...prev, [slug]: data.votes ?? prev[slug] ?? 0 }))
  }

  return { counts, vote }
}

// ─── Markdown renderer ────────────────────────────────────────────────────────

function MD({ children }: { children: string }) {
  return (
    <ReactMarkdown
      components={{
        h1: ({ children }) => <h1 className="mb-3 mt-5 text-lg font-bold text-white first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-2 mt-5 text-base font-semibold text-white first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-1.5 mt-4 text-sm font-semibold text-zinc-200">{children}</h3>,
        p:  ({ children }) => <p className="mb-3 text-sm leading-relaxed text-zinc-300">{children}</p>,
        ul: ({ children }) => <ul className="mb-3 ml-4 list-disc space-y-1 text-sm text-zinc-300">{children}</ul>,
        ol: ({ children }) => <ol className="mb-3 ml-4 list-decimal space-y-1 text-sm text-zinc-300">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        code: ({ children, className }) => {
          const isBlock = className?.includes('language-')
          return isBlock
            ? <code className="block rounded-lg bg-zinc-950 border border-zinc-800 p-3 text-xs font-mono text-emerald-400 whitespace-pre-wrap mb-3">{children}</code>
            : <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs font-mono text-emerald-400">{children}</code>
        },
        pre: ({ children }) => <div className="mb-3">{children}</div>,
        strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
        hr: () => <hr className="my-4 border-zinc-800" />,
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-zinc-700 pl-3 text-sm italic text-zinc-400 mb-3">{children}</blockquote>
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  )
}

// ─── Copy button ──────────────────────────────────────────────────────────────

function CopyBtn({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 2000) }}
      className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 hover:border-zinc-500 hover:text-white"
    >
      {done ? '✓ copied' : `Copy ${label}`}
    </button>
  )
}

// ─── Tag pill ─────────────────────────────────────────────────────────────────

function TagPill({ tag }: { tag: string }) {
  return (
    <span className="inline-flex items-center rounded-md border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
      {tag}
    </span>
  )
}

// ─── Problem modal ────────────────────────────────────────────────────────────

function ProblemModal({
  problem, votes, voted, onVote, onClose,
}: {
  problem: Problem; votes: number; voted: boolean
  onVote: () => void; onClose: () => void
}) {
  const [tab, setTab]  = useState<'problem' | 'rubric'>('problem')
  const router         = useRouter()
  const { isSignedIn } = useUser()

  function useInDashboard() {
    sessionStorage.setItem('is_prefill', JSON.stringify({
      problem: problem.problem,
      rubric:  problem.rubric,
    }))
    onClose()
    router.push(isSignedIn ? '/dashboard' : '/sign-in')
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="flex w-full max-w-2xl flex-col rounded-2xl border border-zinc-700 bg-zinc-900 shadow-2xl max-h-[90vh]">

        {/* Header */}
        <div className="flex items-start justify-between border-b border-zinc-800 px-6 py-4 shrink-0">
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${catColor[problem.category] ?? 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>
                {problem.category}
              </span>
              {problem.tags.map(t => <TagPill key={t} tag={t} />)}
              <span className="text-xs text-zinc-500">{problem.role} · {problem.time}</span>
            </div>
            <h2 className="text-lg font-semibold text-white">{problem.title}</h2>
          </div>
          <button onClick={onClose} className="ml-4 shrink-0 text-zinc-500 hover:text-white text-lg">✕</button>
        </div>

        {/* Tabs + actions */}
        <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3 shrink-0">
          <div className="flex gap-1 rounded-lg border border-zinc-800 bg-zinc-950 p-1">
            {(['problem', 'rubric'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${tab === t ? 'bg-zinc-700 text-white' : 'text-zinc-500 hover:text-zinc-300'}`}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onVote}
              disabled={voted}
              className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors
                ${voted ? 'border-emerald-700 bg-emerald-900/30 text-emerald-400 cursor-default' : 'border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-white'}`}
            >
              {voted ? '▲' : '△'} {votes}
            </button>
            <CopyBtn text={tab === 'problem' ? problem.problem : problem.rubric} label={tab} />
          </div>
        </div>

        {/* Rendered markdown */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <MD>{tab === 'problem' ? problem.problem : problem.rubric}</MD>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-zinc-800 px-6 py-4 shrink-0">
          <p className="text-xs text-zinc-600">Opens dashboard with problem + rubric pre-filled</p>
          <button
            onClick={useInDashboard}
            className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-black hover:bg-zinc-200"
          >
            Use in dashboard →
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Problem card ─────────────────────────────────────────────────────────────

function ProblemCard({
  problem, votes, voted, onVote, onClick,
}: {
  problem: Problem; votes: number; voted: boolean
  onVote: (e: React.MouseEvent) => void; onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      className="group flex cursor-pointer flex-col rounded-xl border border-zinc-800 bg-zinc-900 p-5 hover:border-zinc-600 transition-colors"
    >
      {/* Top row — category + upvote */}
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${catColor[problem.category] ?? 'bg-zinc-800 text-zinc-400 border-zinc-700'}`}>
            {problem.category}
          </span>
          {problem.tags.map(t => <TagPill key={t} tag={t} />)}
        </div>
        <button
          onClick={onVote}
          disabled={voted}
          className={`shrink-0 flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium transition-colors
            ${voted ? 'border-emerald-700 bg-emerald-900/30 text-emerald-400 cursor-default' : 'border-zinc-700 text-zinc-500 hover:border-zinc-500 hover:text-white'}`}
        >
          {voted ? '▲' : '△'} {votes ?? '—'}
        </button>
      </div>

      {/* Title */}
      <h3 className="mb-3 font-semibold text-white group-hover:text-emerald-400 transition-colors leading-snug">
        {problem.title}
      </h3>

      {/* Meta */}
      <div className="mt-auto flex flex-wrap gap-x-2 gap-y-1 text-xs text-zinc-500">
        <span>{problem.role}</span>
        <span>·</span>
        <span>{problem.time}</span>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type SortOption = 'upvotes' | 'az' | 'role'

export default function ProblemsPage() {
  const [activeCategory, setActiveCategory] = useState('all')
  const [activeTag, setActiveTag]           = useState('all')
  const [search, setSearch]                 = useState('')
  const [sort, setSort]                     = useState<SortOption>('upvotes')
  const [selected, setSelected]             = useState<Problem | null>(null)
  const [votedSlugs, setVotedSlugs]         = useState<Set<string>>(new Set())

  const { counts, vote } = useVotes(problems.map(p => p.slug))

  // Tags visible for the active category
  const visibleTags = activeCategory === 'all'
    ? allTags
    : [...new Set(problems.filter(p => p.category === activeCategory).flatMap(p => p.tags))].sort()

  // Reset tag filter when category changes and tag is no longer visible
  useEffect(() => {
    if (activeTag !== 'all' && !visibleTags.includes(activeTag)) setActiveTag('all')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCategory])

  function handleVote(slug: string, e: React.MouseEvent) {
    e.stopPropagation()
    if (votedSlugs.has(slug)) return
    vote(slug)
    setVotedSlugs(prev => new Set([...prev, slug]))
  }

  const filtered = problems
    .filter(p => {
      const matchCat    = activeCategory === 'all' || p.category === activeCategory
      const matchTag    = activeTag === 'all' || p.tags.includes(activeTag)
      const matchSearch = !search || p.title.toLowerCase().includes(search.toLowerCase())
      return matchCat && matchTag && matchSearch
    })
    .sort((a, b) => {
      if (sort === 'upvotes') return (counts[b.slug] ?? 0) - (counts[a.slug] ?? 0)
      if (sort === 'az')     return a.title.localeCompare(b.title)
      if (sort === 'role')   return a.role.localeCompare(b.role)
      return 0
    })

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      <div className="mx-auto max-w-6xl px-6 py-16">

        {/* Header */}
        <div className="mb-10 text-center">
          <h1 className="mb-3 text-3xl font-bold text-white">Interview Problems</h1>
          <p className="text-zinc-400">Real engineering problems with rubrics. One click to use in your dashboard.</p>
          <p className="mt-2 text-sm text-zinc-600">
            {problems.length} problems · community-maintained ·{' '}
            <a
              href="https://github.com/NikhilSKashyap/interviewsignal/tree/main/worked"
              target="_blank" rel="noopener noreferrer"
              className="text-zinc-500 hover:text-zinc-300 underline underline-offset-2"
            >
              add yours via PR ↗
            </a>
          </p>
        </div>

        {/* Filter rows */}
        <div className="mb-8 space-y-3">

          {/* Row 1 — categories + search + sort */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setActiveCategory('all')}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors
                ${activeCategory === 'all' ? 'border-zinc-500 bg-zinc-800 text-white' : 'border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300'}`}
            >
              All <span className="ml-1 text-xs text-zinc-600">{problems.length}</span>
            </button>
            {categories.map(cat => (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                className={`rounded-lg border px-3 py-1.5 text-sm font-medium capitalize transition-colors
                  ${activeCategory === cat ? 'border-zinc-500 bg-zinc-800 text-white' : 'border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300'}`}
              >
                {cat} <span className="ml-1 text-xs text-zinc-600">{problems.filter(p => p.category === cat).length}</span>
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <input
                type="text"
                placeholder="Search..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-32 rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-sm text-white placeholder-zinc-600 focus:border-zinc-600 focus:outline-none"
              />
              <select
                value={sort}
                onChange={e => setSort(e.target.value as SortOption)}
                className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-300 focus:border-zinc-600 focus:outline-none"
              >
                <option value="upvotes">Most upvoted</option>
                <option value="az">A → Z</option>
                <option value="role">By role</option>
              </select>
            </div>
          </div>

          {/* Row 2 — tech stack subtags */}
          {visibleTags.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setActiveTag('all')}
                className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors
                  ${activeTag === 'all' ? 'border-zinc-600 bg-zinc-700 text-white' : 'border-zinc-800 text-zinc-600 hover:border-zinc-700 hover:text-zinc-400'}`}
              >
                All stacks
              </button>
              {visibleTags.map(tag => (
                <button
                  key={tag}
                  onClick={() => setActiveTag(tag)}
                  className={`rounded-md border px-2.5 py-1 text-xs font-medium transition-colors
                    ${activeTag === tag ? 'border-zinc-600 bg-zinc-700 text-white' : 'border-zinc-800 text-zinc-600 hover:border-zinc-700 hover:text-zinc-400'}`}
                >
                  {tag}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Grid */}
        {filtered.length === 0 ? (
          <div className="py-24 text-center text-zinc-600">
            No problems match —{' '}
            <button
              onClick={() => { setSearch(''); setActiveCategory('all'); setActiveTag('all') }}
              className="text-zinc-400 underline hover:text-white"
            >
              clear filters
            </button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map(p => (
              <ProblemCard
                key={p.slug}
                problem={p}
                votes={counts[p.slug] ?? 0}
                voted={votedSlugs.has(p.slug)}
                onVote={e => handleVote(p.slug, e)}
                onClick={() => setSelected(p)}
              />
            ))}
          </div>
        )}

        {/* Contribute CTA */}
        <div className="mt-20 rounded-xl border border-dashed border-zinc-800 p-8 text-center">
          <h3 className="mb-2 font-semibold text-white">Add a problem</h3>
          <p className="mb-1 text-sm text-zinc-400">
            Create <code className="text-zinc-300">worked/&lt;category&gt;/&lt;slug&gt;/PROBLEM.md</code> and <code className="text-zinc-300">RUBRIC.md</code>
          </p>
          <p className="mb-4 text-sm text-zinc-500">
            Add <code className="text-zinc-400">tags: [&apos;Python 3.10+&apos;]</code> (or your stack) to <code className="text-zinc-400">problems.ts</code> and open a PR.
          </p>
          <a
            href="https://github.com/NikhilSKashyap/interviewsignal"
            target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:border-zinc-500 hover:text-white"
          >
            Open a PR on GitHub ↗
          </a>
        </div>
      </div>

      {/* Modal */}
      {selected && (
        <ProblemModal
          problem={selected}
          votes={counts[selected.slug] ?? 0}
          voted={votedSlugs.has(selected.slug)}
          onVote={() => {
            if (votedSlugs.has(selected.slug)) return
            vote(selected.slug)
            setVotedSlugs(prev => new Set([...prev, selected.slug]))
          }}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}

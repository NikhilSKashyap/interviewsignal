'use client'

import { useState } from 'react'
import Link from 'next/link'

// ─── Install one-liner ────────────────────────────────────────────────────────

function InstallBlock() {
  const [copied, setCopied] = useState(false)
  const cmd = 'pip install interviewsignal && interview install'

  function copy() {
    navigator.clipboard.writeText(cmd)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm font-mono max-w-xl w-full">
      <span className="text-zinc-500 select-none">$</span>
      <span className="flex-1 text-emerald-400">{cmd}</span>
      <button
        onClick={copy}
        className="shrink-0 rounded px-2 py-1 text-xs text-zinc-400 hover:text-white hover:bg-zinc-700"
      >
        {copied ? '✓ copied' : 'copy'}
      </button>
    </div>
  )
}

// ─── Comparison table ─────────────────────────────────────────────────────────

const rows = [
  { label: 'Model',              saffron: 'Managed SaaS',           openround: 'Managed SaaS',           is: 'Open-source infrastructure' },
  { label: 'Environment',        saffron: 'Browser IDE sandbox',     openround: 'Hosted browser + CLI',   is: "Candidate's own IDE" },
  { label: 'AI tools',           saffron: 'Platform-controlled',     openround: 'Platform-controlled',    is: 'Any — Claude Code, Codex, Gemini, Cursor' },
  { label: 'Code evolution',     saffron: 'Session replay',          openround: 'Submission trace',       is: 'Per-prompt git commits' },
  { label: 'Tamper evidence',    saffron: 'Session replay (vendor)', openround: 'Not stated',             is: 'Hash-chained + 9 automated flags' },
  { label: 'Assessment quota',   saffron: '5–15/mo + $49 extra',    openround: '5–20/mo + custom',       is: 'Unlimited' },
  { label: 'Pricing',            saffron: 'From $199/mo',            openround: 'From $149/mo',           is: 'Free forever' },
  { label: 'Interview data',     saffron: 'Vendor servers',          openround: 'Vendor servers',         is: 'Your servers' },
  { label: 'Self-hosted',        saffron: 'No',                      openround: 'No',                     is: 'Yes' },
  { label: 'Open source',        saffron: 'No',                      openround: 'No',                     is: 'Yes' },
  { label: 'Trust model',        saffron: 'Vendor-verified',         openround: 'Vendor-verified',        is: 'Cryptographically verifiable' },
]

function ComparisonTable() {
  return (
    <div className="overflow-x-auto w-full">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-zinc-800">
            <th className="py-3 px-4 text-left text-xs font-medium text-zinc-500 w-40"></th>
            <th className="py-3 px-4 text-center text-xs font-medium text-zinc-400">Saffron <span className="text-orange-400">(YC)</span></th>
            <th className="py-3 px-4 text-center text-xs font-medium text-zinc-400">OpenRound</th>
            <th className="py-3 px-4 text-center text-xs font-semibold text-white bg-zinc-800/60 rounded-t-lg">InterviewSignal</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-zinc-800/50">
              <td className="py-3 px-4 text-xs font-medium text-zinc-500">{row.label}</td>
              <td className="py-3 px-4 text-center text-xs text-zinc-400">{row.saffron}</td>
              <td className="py-3 px-4 text-center text-xs text-zinc-400">{row.openround}</td>
              <td className="py-3 px-4 text-center text-xs font-medium text-emerald-400 bg-zinc-800/30">{row.is}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── How it works steps ───────────────────────────────────────────────────────

const steps = [
  {
    step: '01',
    title: 'HM creates an interview',
    body: 'Write a problem, define a rubric, set a time limit. Get back a code like INT-4829-XK. Share it with 5 candidates or 500.',
  },
  {
    step: '02',
    title: 'Candidate installs and starts',
    body: 'One pip install. Candidate works in their own IDE with their own AI tools — Claude Code, Codex, Gemini, Cursor. No sandbox, no browser IDE.',
  },
  {
    step: '03',
    title: 'Every move is captured',
    body: 'Every prompt, tool call, file change, and git commit is logged in a tamper-evident hash chain. The session knows who drove the thinking.',
  },
  {
    step: '04',
    title: 'Candidate submits, HM triages',
    body: 'Auto-graded against the rubric on submit. HM reviews ranked submissions in the dashboard. 200 candidates in 15 minutes.',
  },
]

// ─── Features grid ────────────────────────────────────────────────────────────

const features = [
  {
    icon: '🔗',
    title: 'Hash-chained event log',
    body: 'Every prompt, tool call, and file write is chained. Any tampering breaks the chain. Gaps in the log are their own red flag.',
  },
  {
    icon: '🤖',
    title: 'AI-native grading',
    body: 'Graded on how they used AI — not whether they used it. High-leverage use scores well. Paste-and-accept scores poorly.',
  },
  {
    icon: '📂',
    title: 'Per-prompt git commits',
    body: 'Every candidate prompt silently creates a git commit. You see the code evolve step by step, not just the final diff.',
  },
  {
    icon: '🚩',
    title: '9 automated flags',
    body: 'Too fast, too few interactions, uniform timing, hooks gap, diff mismatch, prompt ratio — all surfaced automatically.',
  },
  {
    icon: '⚡',
    title: 'Zero setup for candidates',
    body: 'pip install, one command, done. Works in Claude Code, Codex, Gemini CLI, Cursor, and Aider.',
  },
  {
    icon: '🔒',
    title: 'Your infra, your data',
    body: 'Community relay on Vercel + Supabase by default. Self-host on Fly.io for full isolation. No telemetry, no tracking.',
  },
]

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function HomePage() {
  return (
    <div className="flex flex-col bg-zinc-950 text-white">

      {/* Hero */}
      <section className="flex flex-col items-center text-center px-6 pt-24 pb-20 border-b border-zinc-800">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-400">
          Free · Open source · No assessment quota
        </div>
        <h1 className="max-w-3xl text-4xl font-bold tracking-tight text-white sm:text-5xl lg:text-6xl">
          When every candidate uses AI,{' '}
          <span className="text-zinc-500">code quality converges.</span>
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-zinc-400 leading-relaxed">
          Output is no longer signal. InterviewSignal captures the full candidate work trail —
          every prompt, tool call, diff, and git commit — and grades how they think, not what they submit.
        </p>
        <div className="mt-8 flex flex-col items-center gap-4 sm:flex-row">
          <InstallBlock />
        </div>
        <div className="mt-6 flex items-center gap-6 text-sm">
          <Link
            href="/dashboard"
            className="rounded-lg bg-white px-5 py-2.5 font-medium text-black hover:bg-zinc-200"
          >
            Open dashboard →
          </Link>
          <a
            href="https://github.com/NikhilSKashyap/interviewsignal"
            target="_blank"
            rel="noopener noreferrer"
            className="text-zinc-400 hover:text-white"
          >
            GitHub ↗
          </a>
        </div>
      </section>

      {/* How it works */}
      <section className="px-6 py-20 border-b border-zinc-800">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-12 text-center text-2xl font-bold text-white">How it works</h2>
          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map(s => (
              <div key={s.step}>
                <p className="mb-3 font-mono text-3xl font-bold text-zinc-700">{s.step}</p>
                <h3 className="mb-2 font-semibold text-white">{s.title}</h3>
                <p className="text-sm text-zinc-400 leading-relaxed">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="px-6 py-20 border-b border-zinc-800">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-12 text-center text-2xl font-bold text-white">The signal stack</h2>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map(f => (
              <div key={f.title} className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
                <p className="mb-3 text-2xl">{f.icon}</p>
                <h3 className="mb-2 font-semibold text-white">{f.title}</h3>
                <p className="text-sm text-zinc-400 leading-relaxed">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Comparison */}
      <section className="px-6 py-20 border-b border-zinc-800">
        <div className="mx-auto max-w-5xl">
          <h2 className="mb-3 text-center text-2xl font-bold text-white">
            vs Saffron and OpenRound
          </h2>
          <p className="mb-10 text-center text-sm text-zinc-500">
            They validate the category. The default shouldn't be another locked-in SaaS.
          </p>
          <div className="rounded-xl border border-zinc-800 overflow-hidden">
            <ComparisonTable />
          </div>
        </div>
      </section>

      {/* Problems CTA */}
      <section className="px-6 py-20 border-b border-zinc-800">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="mb-4 text-2xl font-bold text-white">Ready-to-use interview problems</h2>
          <p className="mb-8 text-zinc-400">
            Backend, MLE, frontend — real engineering problems with rubrics you can copy directly into the dashboard.
          </p>
          <Link
            href="/problems"
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-6 py-3 text-sm font-medium text-zinc-300 hover:border-zinc-500 hover:text-white"
          >
            Browse problems →
          </Link>
        </div>
      </section>

      {/* Final CTA */}
      <section className="px-6 py-24">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="mb-4 text-3xl font-bold text-white">
            Start interviewing in 2 minutes.
          </h2>
          <p className="mb-8 text-zinc-400">
            No platform lock-in. No setup call. No assessment quota. Free forever.
          </p>
          <div className="flex flex-col items-center gap-4">
            <InstallBlock />
            <div className="flex items-center gap-4 text-sm">
              <Link
                href="/dashboard"
                className="rounded-lg bg-white px-5 py-2.5 font-medium text-black hover:bg-zinc-200"
              >
                Open dashboard →
              </Link>
              <a
                href="https://github.com/NikhilSKashyap/interviewsignal"
                target="_blank"
                rel="noopener noreferrer"
                className="text-zinc-400 hover:text-white"
              >
                View on GitHub ↗
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-zinc-800 px-6 py-8 text-center text-xs text-zinc-600">
        InterviewSignal — free, open source, MIT license ·{' '}
        <a href="https://github.com/NikhilSKashyap/interviewsignal" className="hover:text-zinc-400">
          GitHub
        </a>{' '}
        · Built with Claude Code
      </footer>
    </div>
  )
}

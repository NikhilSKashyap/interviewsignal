/**
 * transcriptBuilder.ts
 * Converts a session event log into a readable timeline string.
 * Port of Python interview.core.grader.build_transcript_from_events
 */

type Event = {
  type:      string
  timestamp: number
  payload:   Record<string, unknown>
}

function summariseToolInput(tool: string, inp: Record<string, unknown>): string {
  const t = tool.toLowerCase()
  if (t === 'bash' || t === 'local_shell') {
    const cmd = (inp.command ?? inp.cmd ?? '') as string
    return cmd.slice(0, 80).replace(/\n/g, ' ')
  }
  if (t.includes('read')) return (inp.file_path ?? inp.path ?? '') as string
  if (t.includes('write') || t.includes('edit')) return (inp.file_path ?? inp.path ?? '') as string
  const vals = Object.values(inp).filter(v => typeof v === 'string')
  return vals[0] ? String(vals[0]).slice(0, 80) : ''
}

export function buildTranscript(events: Event[]): string {
  if (!events.length) return '(no events recorded)'

  const startTs = events.find(e => e.type === 'session_start')?.timestamp ?? events[0]?.timestamp ?? 0

  const lines: string[] = []

  for (const e of events) {
    const elapsed = startTs ? ((e.timestamp - startTs) / 60).toFixed(1) : '0.0'
    const tag     = `[T+${elapsed}m]`
    const p       = e.payload ?? {}

    if (e.type === 'session_start') {
      const git    = (p.git_snapshot as Record<string, unknown>) ?? {}
      const commit = ((git.commit as string) ?? 'none').slice(0, 8)
      lines.push(`${tag}  SESSION START  git=${commit}`)

    } else if (e.type === 'user_prompt') {
      const text = ((p.text ?? '') as string).trim().slice(0, 300)
      if (text) lines.push(`${tag}  CANDIDATE:    ${text}`)

    } else if (e.type === 'thinking') {
      const plan = ((p.plan ?? p.text ?? p.reasoning ?? '') as string).trim().slice(0, 300)
      if (plan) lines.push(`${tag}  THINKING:     ${plan}`)

    } else if (e.type === 'assistant_message') {
      const text = ((p.text ?? '') as string).trim().slice(0, 300)
      if (text) lines.push(`${tag}  ASSISTANT:    ${text}`)

    } else if (e.type === 'tool_call') {
      const tool   = (p.tool_name ?? '?') as string
      const inp    = (p.tool_input ?? {}) as Record<string, unknown>
      const detail = summariseToolInput(tool, inp)
      lines.push(`${tag}  → ${tool.padEnd(12)} ${detail}`)

    } else if (e.type === 'tool_result') {
      const tool = (p.tool_name ?? '?') as string
      const summ = p.response_summary as Record<string, unknown> ?? {}
      const out  = Object.values(summ).find(v => typeof v === 'string') ?? ''
      lines.push(`${tag}  ← ${tool.padEnd(12)} ${String(out).slice(0, 80)}`)

    } else if (e.type === 'session_end') {
      const total = p.elapsed_minutes ?? ''
      lines.push(`${tag}  SESSION END  total=${total}min`)
    }
  }

  return lines.join('\n')
}

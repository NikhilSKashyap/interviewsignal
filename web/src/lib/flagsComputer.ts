/**
 * flagsComputer.ts
 * Simplified port of Python interview.core.flags.compute_flags
 */

export type Flag = {
  id:       string
  severity: 'yellow' | 'red'
  label:    string
  detail:   string
}

type Manifest = {
  elapsed_minutes?:  number
  time_limit_minutes?: number
  git_diff_summary?: string
  git_diff_note?:    string
}

export function computeFlags(events: unknown[], manifest: Manifest): Flag[] {
  const flags: Flag[] = []
  const evs = events as Record<string, unknown>[]

  // Overtime
  const elapsed  = manifest.elapsed_minutes  ?? 0
  const limit    = manifest.time_limit_minutes
  if (limit && elapsed > limit) {
    const over = (elapsed - limit).toFixed(1)
    flags.push({
      id: 'overtime', severity: over > '20' ? 'red' : 'yellow',
      label:  'Submitted after time limit',
      detail: `Session ran ${over} min over the ${limit}-minute limit (${elapsed} min total). Score auto-penalized.`,
    })
  }

  // Too fast
  if (limit && elapsed < limit * 0.1) {
    flags.push({
      id: 'too_fast', severity: 'red',
      label:  'Completed very quickly',
      detail: `Session lasted ${elapsed} min — ${((elapsed / limit) * 100).toFixed(0)}% of the ${limit}-minute limit.`,
    })
  } else if (limit && elapsed < limit * 0.2) {
    flags.push({
      id: 'too_fast', severity: 'yellow',
      label:  'Completed unusually quickly',
      detail: `Session lasted ${elapsed} min — ${((elapsed / limit) * 100).toFixed(0)}% of the ${limit}-minute limit.`,
    })
  }

  // Few interactions
  const toolCalls = evs.filter(e => e.type === 'tool_call').length
  if (toolCalls < 3) {
    flags.push({
      id: 'few_interactions', severity: 'red',
      label:  'Very few tool interactions',
      detail: `Only ${toolCalls} tool interaction(s) recorded.`,
    })
  } else if (toolCalls <= 4) {
    flags.push({
      id: 'few_interactions', severity: 'yellow',
      label:  'Few tool interactions',
      detail: `Only ${toolCalls} tool interaction(s) recorded.`,
    })
  }

  // No prompts
  const prompts = evs.filter(e => e.type === 'user_prompt' || e.type === 'thinking').length
  if (prompts === 0) {
    flags.push({
      id: 'no_prompts', severity: 'yellow',
      label:  'No prompts or thinking recorded',
      detail: 'No user_prompt or thinking events found in the session log.',
    })
  }

  // Hooks gap
  if (elapsed >= 5) {
    const timestamps = evs
      .map(e => (e.timestamp as number) * 1000)
      .filter(Boolean)
      .sort((a, b) => a - b)

    if (timestamps.length >= 3) {
      const gaps     = timestamps.slice(1).map((t, i) => t - timestamps[i])
      const maxGap   = Math.max(...gaps)
      const elapsedMs = elapsed * 60 * 1000
      const gapPct   = maxGap / elapsedMs
      const gapMin   = (maxGap / 60000).toFixed(1)

      if (gapPct > 0.5) {
        flags.push({
          id: 'hooks_gap', severity: 'red',
          label:  'Large gap in event stream',
          detail: `Longest gap: ${gapMin} min (${(gapPct * 100).toFixed(0)}% of session). Hooks may have been disabled.`,
        })
      } else if (gapPct > 0.33) {
        flags.push({
          id: 'hooks_gap', severity: 'yellow',
          label:  'Notable gap in event stream',
          detail: `Longest gap: ${gapMin} min (${(gapPct * 100).toFixed(0)}% of session).`,
        })
      }
    }
  }

  // Diff event mismatch
  const diffSummary = manifest.git_diff_summary ?? ''
  const diffNote    = manifest.git_diff_note ?? ''
  if (diffSummary && !['no-git-repo', 'no-changes'].includes(diffNote)) {
    const diffLines = parseInt(diffSummary.split(' ')[0] ?? '0', 10)
    const writeEdits = evs.filter(e => {
      const tool = ((e.payload as Record<string, unknown>)?.tool_name as string ?? '').toLowerCase()
      return e.type === 'tool_call' && (tool.includes('write') || tool.includes('edit'))
    }).length

    if (diffLines >= 100 && writeEdits < 3) {
      flags.push({
        id: 'diff_event_mismatch', severity: 'red',
        label:  'Code changes don\'t match event log',
        detail: `${diffLines} lines changed but only ${writeEdits} Write/Edit call(s) recorded.`,
      })
    } else if (diffLines >= 50 && writeEdits < 3) {
      flags.push({
        id: 'diff_event_mismatch', severity: 'yellow',
        label:  'Code changes may not match event log',
        detail: `${diffLines} lines changed but only ${writeEdits} Write/Edit call(s) recorded.`,
      })
    }
  }

  return flags
}

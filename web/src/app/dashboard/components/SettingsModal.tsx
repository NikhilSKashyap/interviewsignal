'use client'

import { useState, useEffect } from 'react'

type Settings = {
  custom_relay_url:    string
  custom_relay_hm_key: string
  claude_api_key:      string
  has_claude_api_key:  boolean
  hm_key:              string | null
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings]   = useState<Settings | null>(null)
  const [saving, setSaving]       = useState(false)
  const [saved, setSaved]         = useState(false)
  const [keyCopied, setKeyCopied] = useState(false)

  useEffect(() => {
    fetch('/api/settings').then(r => r.json()).then(d => setSettings({
      custom_relay_url:    d.custom_relay_url    ?? '',
      custom_relay_hm_key: d.custom_relay_hm_key ?? '',
      claude_api_key:      '',
      has_claude_api_key:  d.has_claude_api_key  ?? false,
      hm_key:              d.hm_key              ?? null,
    }))
  }, [])

  async function save() {
    if (!settings) return
    setSaving(true)
    const body: Record<string, string> = {
      custom_relay_url:    settings.custom_relay_url,
      custom_relay_hm_key: settings.custom_relay_hm_key,
    }
    if (settings.claude_api_key) body.claude_api_key = settings.claude_api_key
    await fetch('/api/settings', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  function field(label: string, key: keyof Settings, placeholder: string, type = 'text', hint?: string) {
    return (
      <div>
        <label className="mb-1 block text-sm font-medium text-zinc-300">{label}</label>
        {hint && <p className="mb-1.5 text-xs text-zinc-500">{hint}</p>}
        <input
          type={type}
          placeholder={placeholder}
          value={settings?.[key] as string ?? ''}
          onChange={e => setSettings(s => s ? { ...s, [key]: e.target.value } : s)}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:border-zinc-500 focus:outline-none"
        />
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-full max-w-lg rounded-2xl border border-zinc-700 bg-zinc-900 p-6 shadow-2xl">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white">✕</button>
        </div>

        {!settings ? (
          <p className="text-sm text-zinc-500">Loading…</p>
        ) : (
          <div className="space-y-5">

            {/* Grading */}
            <div>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">Grading</p>
              {field(
                'Claude API key',
                'claude_api_key',
                settings.has_claude_api_key ? '••••••••••••••••••••••• (already set)' : 'sk-ant-...',
                'password',
                'Used to auto-grade sessions from this dashboard. Your key, your cost.'
              )}
            </div>

            {/* Power users */}
            <div>
              <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">Custom relay (power users)</p>
              {field('Relay URL', 'custom_relay_url', 'https://my-relay.fly.dev', 'text', 'Leave blank to use the community relay (default).')}
              {field('Relay hm_key', 'custom_relay_hm_key', 'your hm_key from the relay', 'password')}
            </div>

            {/* Local dashboard key */}
            {settings.hm_key && (
              <div>
                <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">Local dashboard</p>
                <p className="mb-2 text-xs text-zinc-500">Add this to <code className="text-zinc-400">~/.interview/config.json</code> as <code className="text-zinc-400">"hm_key"</code></p>
                <div className="flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2">
                  <code className="flex-1 truncate text-xs text-emerald-400">{settings.hm_key}</code>
                  <button
                    onClick={() => { navigator.clipboard.writeText(settings.hm_key!); setKeyCopied(true); setTimeout(() => setKeyCopied(false), 2000) }}
                    className="shrink-0 rounded px-2 py-1 text-xs text-zinc-400 hover:text-white hover:bg-zinc-700"
                  >
                    {keyCopied ? '✓' : 'Copy'}
                  </button>
                </div>
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button onClick={onClose} className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800">Cancel</button>
              <button
                onClick={save}
                disabled={saving}
                className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-black hover:bg-zinc-200 disabled:opacity-50"
              >
                {saved ? '✓ Saved' : saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

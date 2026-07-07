import type { StatusTone } from '@/components/status-dot'

import type { IntegrationEditorInfo, McpDaemonStatus } from './types'

// Pure state -> presentation mapping for the Integrations screen. Kept free of
// React/i18n so it can be unit tested directly (mirrors the cron `job-state.ts`
// convention: one small module owning "what does this state mean visually",
// shared by every place that renders it).

export type EditorConnectionState = 'connected' | 'installed' | 'not-installed'

// Priority mirrors the product rule verbatim: `registered` is authoritative for
// "Connected" (never inferred from `installed` alone); otherwise `installed`
// decides between "installed, not connected" and "not installed".
export function editorConnectionState(
  editor: Pick<IntegrationEditorInfo, 'installed' | 'registered'>
): EditorConnectionState {
  if (editor.registered) {
    return 'connected'
  }

  return editor.installed ? 'installed' : 'not-installed'
}

export const EDITOR_STATE_TONE: Record<EditorConnectionState, StatusTone> = {
  connected: 'good',
  installed: 'warn',
  'not-installed': 'muted'
}

// Known editors get a curated two-letter mark + accent so the grid reads at a
// glance without downloading any logos. Anything the backend reports that
// isn't in this catalog still renders (derived monogram + hashed accent)
// instead of being dropped — new editors show up automatically.
interface EditorCatalogEntry {
  monogram: string
  accent: string
}

const EDITOR_CATALOG: Record<string, EditorCatalogEntry> = {
  'claude-code': { monogram: 'CC', accent: 'bg-orange-500/15 text-orange-400' },
  'claude-desktop': { monogram: 'CD', accent: 'bg-orange-500/15 text-orange-400' },
  cursor: { monogram: 'CU', accent: 'bg-sky-500/15 text-sky-400' },
  vscode: { monogram: 'VS', accent: 'bg-blue-500/15 text-blue-400' },
  codex: { monogram: 'CX', accent: 'bg-emerald-500/15 text-emerald-400' },
  antigravity: { monogram: 'AG', accent: 'bg-violet-500/15 text-violet-400' },
  kiro: { monogram: 'KI', accent: 'bg-pink-500/15 text-pink-400' },
  hermes: { monogram: 'HE', accent: 'bg-amber-500/15 text-amber-400' }
}

const FALLBACK_ACCENTS = [
  'bg-teal-500/15 text-teal-400',
  'bg-indigo-500/15 text-indigo-400',
  'bg-rose-500/15 text-rose-400',
  'bg-lime-500/15 text-lime-500'
]

// FNV-1a-ish small string hash — deterministic, no crypto import needed for a
// cosmetic color pick.
function hashString(value: string): number {
  let hash = 0

  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0
  }

  return Math.abs(hash)
}

export function editorMonogram(id: string, name: string): string {
  const known = EDITOR_CATALOG[id]

  if (known) {
    return known.monogram
  }

  const letters = name
    .trim()
    .split(/\s+/)
    .map(word => word[0])
    .filter((char): char is string => Boolean(char))
    .slice(0, 2)
    .join('')
    .toUpperCase()

  return letters || id.slice(0, 2).toUpperCase() || '?'
}

export function editorAccentClass(id: string): string {
  const known = EDITOR_CATALOG[id]

  if (known) {
    return known.accent
  }

  return FALLBACK_ACCENTS[hashString(id) % FALLBACK_ACCENTS.length]
}

export function daemonTone(status: McpDaemonStatus | null | undefined): StatusTone {
  if (!status) {
    return 'muted'
  }

  return status.running ? 'good' : 'bad'
}

// Compact duration since `startedAt` (ISO string). Returns null for a missing
// or unparsable timestamp so the caller can fall back to hiding the uptime
// clause instead of rendering "NaNs".
export function formatDaemonUptime(startedAt: string | undefined, nowMs: number = Date.now()): null | string {
  if (!startedAt) {
    return null
  }

  const startedMs = Date.parse(startedAt)

  if (Number.isNaN(startedMs)) {
    return null
  }

  const deltaSec = Math.max(0, Math.floor((nowMs - startedMs) / 1000))

  if (deltaSec < 60) {
    return `${deltaSec}s`
  }

  const minutes = Math.floor(deltaSec / 60)

  if (minutes < 60) {
    return `${minutes}m`
  }

  const hours = Math.floor(minutes / 60)
  const remMinutes = minutes % 60

  if (hours < 24) {
    return remMinutes ? `${hours}h ${remMinutes}m` : `${hours}h`
  }

  const days = Math.floor(hours / 24)
  const remHours = hours % 24

  return remHours ? `${days}d ${remHours}h` : `${days}d`
}

// Stable sort so the grid doesn't reshuffle on every poll: connected first,
// then installed-not-connected, then not-installed; alphabetical within a tier.
export function sortEditorsForDisplay(editors: IntegrationEditorInfo[]): IntegrationEditorInfo[] {
  const rank: Record<EditorConnectionState, number> = { connected: 0, installed: 1, 'not-installed': 2 }

  return [...editors].sort((a, b) => {
    const rankDelta = rank[editorConnectionState(a)] - rank[editorConnectionState(b)]

    return rankDelta !== 0 ? rankDelta : a.name.localeCompare(b.name)
  })
}

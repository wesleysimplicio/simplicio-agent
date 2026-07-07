import { describe, expect, it } from 'vitest'

import {
  daemonTone,
  editorAccentClass,
  editorConnectionState,
  editorMonogram,
  formatDaemonUptime,
  sortEditorsForDisplay
} from './editor-presentation'
import type { IntegrationEditorInfo } from './types'

function editor(overrides: Partial<IntegrationEditorInfo>): IntegrationEditorInfo {
  return {
    id: 'cursor',
    name: 'Cursor',
    installed: true,
    registered: true,
    configPath: '/tmp/config.json',
    ...overrides
  }
}

describe('editorConnectionState', () => {
  it('is "connected" whenever registered is true, even if installed is false', () => {
    expect(editorConnectionState({ installed: false, registered: true })).toBe('connected')
  })

  it('is "installed" when installed but not registered', () => {
    expect(editorConnectionState({ installed: true, registered: false })).toBe('installed')
  })

  it('is "not-installed" when neither installed nor registered', () => {
    expect(editorConnectionState({ installed: false, registered: false })).toBe('not-installed')
  })

  // The one honesty rule this screen must never violate: "Connected" is only
  // ever driven by the backend's `registered` flag, never inferred.
  it('never reports "connected" from installed alone', () => {
    expect(editorConnectionState({ installed: true, registered: false })).not.toBe('connected')
  })
})

describe('editorMonogram', () => {
  it('uses the curated monogram for known editors', () => {
    expect(editorMonogram('claude-code', 'Claude Code')).toBe('CC')
    expect(editorMonogram('claude-desktop', 'Claude Desktop')).toBe('CD')
    expect(editorMonogram('vscode', 'VS Code')).toBe('VS')
  })

  it('derives a monogram from the name for unknown editors', () => {
    expect(editorMonogram('some-new-tool', 'Some Tool')).toBe('ST')
  })

  it('falls back to the id when the name has no usable letters', () => {
    expect(editorMonogram('zeta', '')).toBe('ZE')
  })
})

describe('editorAccentClass', () => {
  it('is deterministic for the same id', () => {
    expect(editorAccentClass('kiro')).toBe(editorAccentClass('kiro'))
  })

  it('returns a class string for an unknown id instead of throwing', () => {
    expect(typeof editorAccentClass('totally-unknown-editor')).toBe('string')
  })
})

describe('daemonTone', () => {
  it('is "muted" when there is no status (backend unavailable)', () => {
    expect(daemonTone(null)).toBe('muted')
    expect(daemonTone(undefined)).toBe('muted')
  })

  it('is "good" when running', () => {
    expect(daemonTone({ running: true, restarts: 0 })).toBe('good')
  })

  it('is "bad" when stopped', () => {
    expect(daemonTone({ running: false, restarts: 2, lastError: 'boom' })).toBe('bad')
  })
})

describe('formatDaemonUptime', () => {
  const now = Date.parse('2026-07-07T12:00:00Z')

  it('returns null when startedAt is missing', () => {
    expect(formatDaemonUptime(undefined, now)).toBeNull()
  })

  it('returns null when startedAt is unparsable', () => {
    expect(formatDaemonUptime('not-a-date', now)).toBeNull()
  })

  it('formats seconds', () => {
    expect(formatDaemonUptime('2026-07-07T11:59:30Z', now)).toBe('30s')
  })

  it('formats minutes', () => {
    expect(formatDaemonUptime('2026-07-07T11:55:00Z', now)).toBe('5m')
  })

  it('formats hours and minutes', () => {
    expect(formatDaemonUptime('2026-07-07T09:30:00Z', now)).toBe('2h 30m')
  })

  it('formats whole hours without a minutes clause', () => {
    expect(formatDaemonUptime('2026-07-07T09:00:00Z', now)).toBe('3h')
  })

  it('formats days and hours', () => {
    expect(formatDaemonUptime('2026-07-05T06:00:00Z', now)).toBe('2d 6h')
  })
})

describe('sortEditorsForDisplay', () => {
  it('orders connected, then installed, then not-installed, alphabetically within each tier', () => {
    const editors = [
      editor({ id: 'z', name: 'Zeta', installed: false, registered: false }),
      editor({ id: 'a', name: 'Alpha', installed: true, registered: true }),
      editor({ id: 'm', name: 'Mid', installed: true, registered: false }),
      editor({ id: 'b', name: 'Beta', installed: true, registered: true })
    ]

    expect(sortEditorsForDisplay(editors).map(e => e.id)).toEqual(['a', 'b', 'm', 'z'])
  })

  it('does not mutate the input array', () => {
    const editors = [editor({ id: 'z', name: 'Zeta' }), editor({ id: 'a', name: 'Alpha' })]
    const original = [...editors]
    sortEditorsForDisplay(editors)
    expect(editors).toEqual(original)
  })
})

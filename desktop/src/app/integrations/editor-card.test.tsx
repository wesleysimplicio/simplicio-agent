import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { en } from '@/i18n/en'

import { EditorCard } from './editor-card'
import type { IntegrationEditorInfo } from './types'

afterEach(() => {
  cleanup()
})

function editor(overrides: Partial<IntegrationEditorInfo> = {}): IntegrationEditorInfo {
  return {
    configPath: '/tmp/config.json',
    id: 'claude-code',
    installed: true,
    name: 'Claude Code',
    registered: true,
    ...overrides
  }
}

// The `live` prop is a cosmetic cross-reference from the live MCP
// connections poll (see index.tsx / mcp-connections-presentation.ts) onto
// this otherwise-unrelated static card — it must never change the
// registered/installed state the card already reports.
describe('EditorCard live badge', () => {
  it('renders no live indicator by default', () => {
    render(<EditorCard copy={en.integrations} editor={editor()} entered index={0} />)

    expect(screen.queryByTitle(en.integrations.mcpLive.liveNowTooltip)).toBeNull()
  })

  it('renders the live indicator when live=true, without altering the registered state label', () => {
    render(<EditorCard copy={en.integrations} editor={editor()} entered index={0} live />)

    expect(screen.getByTitle(en.integrations.mcpLive.liveNowTooltip)).toBeTruthy()
    expect(screen.getByText(en.integrations.stateConnected)).toBeTruthy()
  })
})

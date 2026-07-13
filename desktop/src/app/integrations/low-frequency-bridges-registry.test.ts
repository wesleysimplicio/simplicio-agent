import { describe, expect, it } from 'vitest'

import {
  bridgeBadgeLabel,
  findLowFrequencyBridge,
  LOW_FREQUENCY_BRIDGES,
  pendingMcpDomains
} from './low-frequency-bridges-registry'

describe('LOW_FREQUENCY_BRIDGES', () => {
  it('gives every entry a non-empty CLI fallback command', () => {
    for (const entry of LOW_FREQUENCY_BRIDGES) {
      expect(entry.cliFallback.length).toBeGreaterThan(0)
    }
  })

  it('mcp entries have a tool name, cli-fallback entries have null', () => {
    for (const entry of LOW_FREQUENCY_BRIDGES) {
      if (entry.status === 'mcp') {
        expect(entry.mcpTool).not.toBeNull()
      } else {
        expect(entry.mcpTool).toBeNull()
      }
    }
  })

  it('has no duplicate domains', () => {
    const domains = LOW_FREQUENCY_BRIDGES.map(e => e.domain)

    expect(new Set(domains).size).toBe(domains.length)
  })
})

describe('findLowFrequencyBridge', () => {
  it('finds a known domain', () => {
    expect(findLowFrequencyBridge('cron')?.status).toBe('mcp')
  })

  it('is case- and whitespace-insensitive', () => {
    expect(findLowFrequencyBridge('  Workflow ')?.domain).toBe('workflow')
  })

  it('returns null for an unknown domain', () => {
    expect(findLowFrequencyBridge('not-a-domain')).toBeNull()
  })
})

describe('bridgeBadgeLabel', () => {
  it('labels an MCP entry with its tool name', () => {
    const entry = findLowFrequencyBridge('gateway')

    expect(entry).not.toBeNull()
    expect(bridgeBadgeLabel(entry!)).toBe('MCP: gateway_status')
  })

  it('labels a CLI-fallback entry as fallback available, not missing', () => {
    const entry = findLowFrequencyBridge('workflow')

    expect(entry).not.toBeNull()
    expect(bridgeBadgeLabel(entry!)).toBe('CLI fallback available')
  })
})

describe('pendingMcpDomains', () => {
  it('excludes the domains that already have an MCP tool', () => {
    const pending = pendingMcpDomains()

    expect(pending.some(e => e.domain === 'cron')).toBe(false)
    expect(pending.some(e => e.domain === 'gateway')).toBe(false)
    expect(pending.some(e => e.domain === 'hooks')).toBe(false)
  })

  it('includes workflow and issue-factory', () => {
    const domains = pendingMcpDomains().map(e => e.domain)

    expect(domains).toContain('workflow')
    expect(domains).toContain('issue-factory')
  })
})

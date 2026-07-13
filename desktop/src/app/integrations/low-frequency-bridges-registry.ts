// Static registry of the low-frequency command tail (issue #99): cron,
// gateway, workflow, issue-factory, agent, desktop, plan/decide/sprint/
// learn, doctor/hooks/tokio-runtime/health/settings.
//
// This is the desktop-side mirror of `mcp_low_freq_bridges.py`'s
// `LOW_FREQUENCY_DOMAINS` / `list_bridges()` and
// `docs/mcp-low-frequency-bridges.md`'s classification table. Keep the two
// in sync by hand when a domain graduates from CLI fallback to an MCP
// tool -- there is deliberately no runtime fetch here, because this list
// needs to render even when the gateway/runtime the numbers would come
// from is unreachable (that unreachability is exactly the case the
// "fallback available" badge exists to cover).
//
// Purpose: so the desktop app can show "MCP" vs "CLI fallback available"
// for these rare commands instead of looking like it silently dropped
// capability -- see the Desktop acceptance criterion on issue #99.

export type LowFrequencyBridgeStatus = 'cli-fallback' | 'mcp'

export interface LowFrequencyBridgeEntry {
  /** cron, gateway, workflow, issue-factory, agent, desktop, plan, decide,
   * sprint, learn, doctor, tokio-runtime, health, settings. */
  domain: string
  /** Exact CLI command to run when status is 'cli-fallback'. Always
   * present -- a fallback entry with no command would defeat the point. */
  cliFallback: string
  /** MCP tool name when status is 'mcp', else null. */
  mcpTool: null | string
  status: LowFrequencyBridgeStatus
}

// Source of truth: docs/mcp-low-frequency-bridges.md's classification
// table + mcp_low_freq_bridges.py's LOW_FREQUENCY_DOMAINS /
// _CLI_FALLBACK_COMMANDS.
export const LOW_FREQUENCY_BRIDGES: readonly LowFrequencyBridgeEntry[] = [
  {
    cliFallback: 'simplicio-agent cron add|tick|run|pause|resume|remove',
    domain: 'cron',
    mcpTool: 'cron_status',
    status: 'mcp'
  },
  {
    cliFallback: 'simplicio-agent gateway setup|start|stop|restart',
    domain: 'gateway',
    mcpTool: 'gateway_status',
    status: 'mcp'
  },
  {
    cliFallback: 'simplicio-agent hooks test|revoke',
    domain: 'hooks',
    mcpTool: 'hooks_status',
    status: 'mcp'
  },
  {
    cliFallback: 'simplicio workflow run|resume|retry|watch --repo <path> [--json]',
    domain: 'workflow',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio issue-factory run|claim|pr-handoff|comment --repo <path> [--json]',
    domain: 'issue-factory',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio agents delegate <goal>|children|pause|resume|interrupt [--json]',
    domain: 'agent',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio app list|info|doctor|setup|run <name> [--json]',
    domain: 'desktop',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio plan "<task>" --repo <path> [--json]',
    domain: 'plan',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio decide "<task>" --repo <path> [--json]',
    domain: 'decide',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio sprint <sprint-path-or-text> --repo <path> [--json]',
    domain: 'sprint',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio learn from-run <run-id> [--scope project|local|global]',
    domain: 'learn',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio-agent doctor [--fix]',
    domain: 'doctor',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio status [--json] [--watch]',
    domain: 'tokio-runtime',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio-agent doctor [--fix]',
    domain: 'health',
    mcpTool: null,
    status: 'cli-fallback'
  },
  {
    cliFallback: 'simplicio-agent config get|set <key> [<value>]',
    domain: 'settings',
    mcpTool: null,
    status: 'cli-fallback'
  }
]

/** Look up one domain's entry, or null when the domain isn't in the registry. */
export function findLowFrequencyBridge(domain: string): LowFrequencyBridgeEntry | null {
  const normalized = domain.trim().toLowerCase()

  return LOW_FREQUENCY_BRIDGES.find(entry => entry.domain === normalized) ?? null
}

/** Human-readable badge text for a bridge entry's card in the desktop UI. */
export function bridgeBadgeLabel(entry: LowFrequencyBridgeEntry): string {
  return entry.status === 'mcp' ? `MCP: ${entry.mcpTool}` : 'CLI fallback available'
}

/** Domains still awaiting an MCP tool -- the live "what's left" list for
 * the desktop's low-frequency-commands panel. */
export function pendingMcpDomains(): readonly LowFrequencyBridgeEntry[] {
  return LOW_FREQUENCY_BRIDGES.filter(entry => entry.status === 'cli-fallback')
}

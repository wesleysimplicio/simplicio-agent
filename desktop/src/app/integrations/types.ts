// Integrations screen — data contract for the `window.simplicioSavings` preload
// bridge that another in-flight change wires up in electron/preload. That
// change owns `global.d.ts`; this module intentionally does NOT declare a
// global `Window.simplicioSavings` augmentation (to avoid a duplicate/
// conflicting declaration landing from two places at once). Instead it reads
// the bridge defensively through `getIntegrationsApi()`, which degrades to
// `undefined` whenever the bridge — or any individual method on it — hasn't
// landed yet, so this screen never assumes the shape beyond what it needs.

export interface IntegrationEditorInfo {
  id: string
  name: string
  installed: boolean
  registered: boolean
  configPath: string
}

interface EditorsDetectOk {
  ok: true
  editors: IntegrationEditorInfo[]
}

interface EditorsDetectFailure {
  ok: false
  error: string
}

export type EditorsDetectResponse = EditorsDetectFailure | EditorsDetectOk

interface McpRegisterOk {
  ok: true
  registered: string[]
  skipped: string[]
  raw: string
}

interface McpRegisterFailure {
  ok: false
  error: string
}

export type McpRegisterResponse = McpRegisterFailure | McpRegisterOk

export interface McpDaemonStatus {
  running: boolean
  pid?: number
  restarts: number
  startedAt?: string
  lastError?: string
}

export interface SimplicioSavingsIntegrationsApi {
  editorsDetect?: () => Promise<EditorsDetectResponse>
  mcpRegister?: () => Promise<McpRegisterResponse>
  mcpDaemonStatus?: () => Promise<McpDaemonStatus>
}

interface SimplicioSavingsWindow {
  simplicioSavings?: SimplicioSavingsIntegrationsApi
}

/** Defensive accessor — never throws, works whether or not the bridge (or
 *  parts of it) has landed yet. */
export function getIntegrationsApi(): SimplicioSavingsIntegrationsApi | undefined {
  if (typeof window === 'undefined') {
    return undefined
  }

  return (window as unknown as SimplicioSavingsWindow).simplicioSavings
}

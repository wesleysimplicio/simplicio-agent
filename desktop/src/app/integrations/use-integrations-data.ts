import { useCallback, useEffect, useRef, useState } from 'react'

import { getIntegrationsApi, type IntegrationEditorInfo, type McpDaemonStatus } from './types'

// Same cadence as the sidebar's cron-job poll (desktop-controller.tsx) — long
// enough to be cheap, short enough that a deploy elsewhere (another window,
// `simplicio mcp register` from a terminal) shows up without a manual refresh.
const POLL_INTERVAL_MS = 20_000

// Sentinel for "the deploy action itself has no backend to call" (as opposed
// to a real error surfaced by `mcp_register`), so the view can render the
// translated "backend unavailable" copy instead of an empty/undefined message.
export const DEPLOY_BACKEND_UNAVAILABLE = '__integrations_backend_unavailable__'

export interface DeployOutcome {
  registered: string[]
  skipped: string[]
  error?: string
}

export function useIntegrationsData() {
  const apiRef = useRef(getIntegrationsApi())
  apiRef.current = getIntegrationsApi()
  const apiAvailable = Boolean(apiRef.current)

  const [editors, setEditors] = useState<IntegrationEditorInfo[] | null>(null)
  const [daemonStatus, setDaemonStatus] = useState<McpDaemonStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [detectError, setDetectError] = useState<null | string>(null)
  const [deploying, setDeploying] = useState(false)
  const [deployOutcome, setDeployOutcome] = useState<DeployOutcome | null>(null)

  const refresh = useCallback(async () => {
    const api = apiRef.current

    if (!api?.editorsDetect) {
      setEditors(null)
      setDetectError(null)
    } else {
      try {
        const result = await api.editorsDetect()

        if (result.ok) {
          setEditors(result.editors)
          setDetectError(null)
        } else {
          setDetectError(result.error)
        }
      } catch (err) {
        setDetectError(err instanceof Error ? err.message : String(err))
      }
    }

    if (!api?.mcpDaemonStatus) {
      setDaemonStatus(null)
    } else {
      try {
        setDaemonStatus(await api.mcpDaemonStatus())
      } catch {
        // Daemon status is best-effort telemetry — a failure here degrades to
        // the "unknown" (muted) tone rather than blocking the whole screen.
        setDaemonStatus(null)
      }
    }

    setLoading(false)
  }, [])

  useEffect(() => {
    void refresh()
    // Runs once on mount; `refresh` closes over a ref so it never goes stale.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!apiAvailable) {
      return
    }

    const tick = () => {
      if (document.visibilityState === 'visible') {
        void refresh()
      }
    }

    const intervalId = window.setInterval(tick, POLL_INTERVAL_MS)
    document.addEventListener('visibilitychange', tick)

    return () => {
      window.clearInterval(intervalId)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [apiAvailable, refresh])

  const deploy = useCallback(async () => {
    const api = apiRef.current

    if (!api?.mcpRegister) {
      setDeployOutcome({ registered: [], skipped: [], error: DEPLOY_BACKEND_UNAVAILABLE })

      return
    }

    setDeploying(true)

    try {
      const result = await api.mcpRegister()

      if (result.ok) {
        setDeployOutcome({ registered: result.registered, skipped: result.skipped })
        await refresh()
      } else {
        setDeployOutcome({ registered: [], skipped: [], error: result.error })
      }
    } catch (err) {
      setDeployOutcome({ registered: [], skipped: [], error: err instanceof Error ? err.message : String(err) })
    } finally {
      setDeploying(false)
    }
  }, [refresh])

  return {
    apiAvailable,
    daemonStatus,
    deploy,
    deployOutcome,
    deploying,
    detectError,
    editors,
    loading,
    refresh
  }
}

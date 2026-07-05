import React, { useState, useEffect } from 'react'

export default function TokenMonitor() {
  const [stats, setStats] = useState({ used: 0, limit: 100000, cost: 0, period: 'month' })
  const [history, setHistory] = useState([])

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch('http://127.0.0.1:6119/v1/status')
        const data = await res.json()
        if (data?.token_usage) setStats(data.token_usage)
      } catch {}
    }
    fetchStats()
    const interval = setInterval(fetchStats, 30000)
    return () => clearInterval(interval)
  }, [])

  const pct = stats.limit > 0 ? Math.round((stats.used / stats.limit) * 100) : 0

  return (
    <div style={{
      padding: 24, color: '#e8e8f0', fontFamily: 'system-ui, sans-serif',
      maxWidth: 500, margin: 'auto'
    }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>📊 Token Monitor</h1>
      <p style={{ fontSize: 13, color: '#5a5a7a', marginBottom: 24 }}>
        Uso de tokens neste {stats.period}
      </p>

      <div style={{
        background: '#1a1a2e', borderRadius: 12, padding: 20, marginBottom: 16
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
          <span>{stats.used.toLocaleString()} tokens</span>
          <span style={{ color: '#5a5a7a' }}>{stats.limit.toLocaleString()} limite</span>
        </div>
        <div style={{
          height: 8, background: '#2a2a3e', borderRadius: 4, overflow: 'hidden'
        }}>
          <div style={{
            width: `${Math.min(pct, 100)}%`, height: '100%',
            background: pct > 80 ? '#ef4444' : pct > 50 ? '#fb923c' : '#22d3ee',
            borderRadius: 4, transition: 'width 0.5s'
          }} />
        </div>
        <p style={{ fontSize: 12, color: '#5a5a7a', marginTop: 8 }}>
          {pct}% utilizado · Custo estimado: ${stats.cost.toFixed(2)}
        </p>
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8
      }}>
        {['Hoje', '7 dias', '30 dias'].map(p => (
          <div key={p} style={{
            background: '#1a1a2e', borderRadius: 8, padding: 12, textAlign: 'center'
          }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#22d3ee' }}>
              {(Math.random() * 10000 + 1000).toLocaleString()}
            </div>
            <div style={{ fontSize: 11, color: '#5a5a7a' }}>{p}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

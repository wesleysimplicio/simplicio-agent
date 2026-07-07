import { useEffect, useRef, useState } from 'react'

import type { CumulativePoint } from '@/app/savings/parse'
import { formatTokens } from '@/app/savings/format'
import { cn } from '@/lib/utils'

interface SavingsChartProps {
  className?: string
  points: readonly CumulativePoint[]
}

const WIDTH = 640
const HEIGHT = 160
const PAD_X = 8
const PAD_Y = 12

function buildPath(points: readonly CumulativePoint[]): { line: string; area: string } {
  if (points.length === 0) {
    return { area: '', line: '' }
  }

  const minT = points[0].timestampMs
  const maxT = points[points.length - 1].timestampMs
  const maxV = Math.max(...points.map(p => p.cumulativeSaved), 1)
  const spanT = Math.max(1, maxT - minT)

  const xOf = (t: number) => PAD_X + ((t - minT) / spanT) * (WIDTH - PAD_X * 2)
  const yOf = (v: number) => HEIGHT - PAD_Y - (v / maxV) * (HEIGHT - PAD_Y * 2)

  const coords = points.map(p => [xOf(p.timestampMs), yOf(p.cumulativeSaved)] as const)

  const line = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ')

  const first = coords[0]
  const last = coords[coords.length - 1]
  const area = `${line} L${last[0].toFixed(2)},${HEIGHT - PAD_Y} L${first[0].toFixed(2)},${HEIGHT - PAD_Y} Z`

  return { area, line }
}

// Pure-SVG cumulative-savings trend line (no charting dependency in this
// project). The stroke draws in on mount via stroke-dashoffset, and is
// skipped entirely under prefers-reduced-motion (renders fully drawn).
export function SavingsChart({ className, points }: SavingsChartProps) {
  const pathRef = useRef<SVGPathElement>(null)
  const [drawn, setDrawn] = useState(false)

  useEffect(() => {
    setDrawn(false)
    const id = requestAnimationFrame(() => setDrawn(true))

    return () => cancelAnimationFrame(id)
  }, [points])

  if (points.length < 2) {
    return null
  }

  const { area, line } = buildPath(points)
  const maxV = Math.max(...points.map(p => p.cumulativeSaved), 1)
  const length = pathRef.current?.getTotalLength() ?? 2000

  return (
    <svg
      aria-hidden="true"
      className={cn('h-40 w-full overflow-visible', className)}
      preserveAspectRatio="none"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
    >
      <defs>
        <linearGradient id="savings-chart-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--savings-accent, #39ff14)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="var(--savings-accent, #39ff14)" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Baseline grid: zero line + max line, for scale reference. */}
      <line stroke="currentColor" strokeOpacity="0.08" x1={PAD_X} x2={WIDTH - PAD_X} y1={HEIGHT - PAD_Y} y2={HEIGHT - PAD_Y} />
      <text fill="currentColor" fillOpacity="0.4" fontSize="9" x={PAD_X} y={PAD_Y - 2}>
        {formatTokens(maxV)}
      </text>

      <path d={area} fill="url(#savings-chart-fill)" stroke="none" />
      <path
        className="savings-chart-line"
        d={line}
        fill="none"
        ref={pathRef}
        stroke="var(--savings-accent, #39ff14)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        style={{
          strokeDasharray: length,
          strokeDashoffset: drawn ? 0 : length,
          transition: 'stroke-dashoffset 900ms cubic-bezier(0.16, 1, 0.3, 1)'
        }}
      />
    </svg>
  )
}

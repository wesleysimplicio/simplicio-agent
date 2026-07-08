import type { DashboardTimeseriesPoint } from '@/app/savings/dashboard-parse'

// "Heartbeat" mini-chart for Live Activity's timeseries buckets — pure SVG,
// no charting dependency (same approach as `SavingsChart`). Unlike that
// component's one-time draw-in, this one redraws its `d` attribute on every
// poll: the `transition: d` on the <path> animates the line smoothly from
// its old shape to the new one, which is what makes it read as "live"
// rather than a static snapshot that occasionally jumps.

interface LiveHeartbeatChartProps {
  points: readonly DashboardTimeseriesPoint[]
}

const WIDTH = 320
const HEIGHT = 64
const PAD_X = 4
const PAD_Y = 6

function buildPath(points: readonly DashboardTimeseriesPoint[]): string {
  const usable = points.filter((p): p is DashboardTimeseriesPoint & { saved: number } => p.saved !== null)

  if (usable.length === 0) {
    return ''
  }

  const maxV = Math.max(...usable.map(p => p.saved), 1)
  const n = usable.length
  const xOf = (i: number) => (n === 1 ? WIDTH / 2 : PAD_X + (i / (n - 1)) * (WIDTH - PAD_X * 2))
  const yOf = (v: number) => HEIGHT - PAD_Y - (v / maxV) * (HEIGHT - PAD_Y * 2)

  return usable.map((p, i) => `${i === 0 ? 'M' : 'L'}${xOf(i).toFixed(2)},${yOf(p.saved).toFixed(2)}`).join(' ')
}

export function LiveHeartbeatChart({ points }: LiveHeartbeatChartProps) {
  const d = buildPath(points)

  if (!d) {
    return null
  }

  return (
    <svg
      aria-hidden="true"
      className="h-16 w-full overflow-visible"
      preserveAspectRatio="none"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
    >
      <line stroke="currentColor" strokeOpacity="0.08" x1={PAD_X} x2={WIDTH - PAD_X} y1={HEIGHT - PAD_Y} y2={HEIGHT - PAD_Y} />
      <path
        className="savings-heartbeat-line"
        d={d}
        fill="none"
        stroke="var(--savings-accent, #39ff14)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        style={{ transition: 'd 500ms ease-out' }}
      />
    </svg>
  )
}

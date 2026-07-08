import { useEffect, useState } from 'react'

// One-shot "Neon Burst" celebration: a radial explosion of green particles
// plus an expanding shock ring, played once on mount and then unmounted.
// Mount it keyed by useThresholdCrossing's burstKey so each false→true
// crossing replays it. Purely decorative (aria-hidden, pointer-events-none);
// the caller never mounts it under prefers-reduced-motion (burstKey stays 0).

interface NeonBurstProps {
  /** Mini variant for session badges: fewer, closer particles. */
  mini?: boolean
}

const FULL_PARTICLES = 22
const MINI_PARTICLES = 10

// Deterministic per-index pseudo-randomness: golden-angle spacing plus small
// modular jitter. Stable across renders (no Math.random in render paths).
function particleStyle(index: number, mini: boolean): React.CSSProperties {
  const angle = index * 137.5 * (Math.PI / 180)
  const distance = (mini ? 24 : 40) + ((index * 37) % (mini ? 28 : 50))
  const size = 2 + ((index * 13) % 4)
  const hue = index % 3

  return {
    animationDelay: `${(index % 5) * 18}ms`,
    background:
      hue === 0 ? 'var(--savings-accent, #39ff14)' : hue === 1 ? '#22c55e' : 'color-mix(in srgb, var(--savings-accent, #39ff14) 60%, #ffffff)',
    height: size,
    width: size,
    ['--burst-dx' as string]: `${Math.cos(angle) * distance}px`,
    ['--burst-dy' as string]: `${Math.sin(angle) * distance}px`
  }
}

export function NeonBurst({ mini = false }: NeonBurstProps) {
  const [done, setDone] = useState(false)
  const count = mini ? MINI_PARTICLES : FULL_PARTICLES

  useEffect(() => {
    const id = window.setTimeout(() => setDone(true), 1000)

    return () => window.clearTimeout(id)
  }, [])

  if (done) {
    return null
  }

  return (
    <span aria-hidden="true" className="pointer-events-none absolute inset-0 grid place-items-center overflow-visible">
      <svg
        className="absolute overflow-visible"
        height={mini ? 80 : 240}
        viewBox={mini ? '-40 -40 80 80' : '-120 -120 240 240'}
        width={mini ? 80 : 240}
      >
        <circle
          className="savings-burst-ring"
          cx="0"
          cy="0"
          fill="none"
          r="1"
          stroke="var(--savings-accent, #39ff14)"
          strokeWidth="2"
          style={{ ['--ring-scale' as string]: mini ? 36 : 110 }}
        />
      </svg>
      {Array.from({ length: count }, (_, index) => (
        <span className="savings-burst-particle absolute rounded-full" key={index} style={particleStyle(index, mini)} />
      ))}
    </span>
  )
}

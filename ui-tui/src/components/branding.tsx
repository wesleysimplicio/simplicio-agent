import { Box, Text, useStdout } from '@hermes/ink'
import { useEffect, useState } from 'react'
import unicodeSpinners from 'unicode-animations'

import { artWidth, caduceus, CADUCEUS_WIDTH, logo, LOGO_WIDTH } from '../banner.js'
import { flat } from '../lib/text.js'
import type { Theme } from '../theme.js'
import type { PanelSection, SessionInfo } from '../types.js'

const LOADER_TICK_MS = 120

function InlineLoader({ label, t }: { label: string; t: Theme }) {
  const [tick, setTick] = useState(0)
  const spinner = unicodeSpinners.braille
  const frame = spinner.frames[tick % spinner.frames.length] ?? '⠋'

  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), Math.max(LOADER_TICK_MS, spinner.interval))

    return () => clearInterval(id)
  }, [spinner.interval])

  return (
    <Text color={t.color.muted} wrap="truncate">
      <Text color={t.color.accent}>{frame}</Text> {label}
    </Text>
  )
}

export function ArtLines({ lines }: { lines: [string, string][] }) {
  return (
    <Box flexDirection="column" height={lines.length} opaque width={artWidth(lines)}>
      {lines.map(([c, text], i) => (
        <Text color={c} key={i} wrap="truncate-end">
          {text}
        </Text>
      ))}
    </Box>
  )
}

// Responsive Banner: full art -> compact rule -> text -> hidden.
const TAG_FULL = 'Simplicio Agent'
const TAG_MID = 'Simplicio Agent'
const TAG_TINY = 'Simplicio Agent'
const HIDE_BELOW = 34
const COMPACT_FROM = 58

const clip = (s: string, w: number) => (w <= 0 ? '' : s.length > w ? `${s.slice(0, Math.max(0, w - 1))}…` : s)

const centerIn = (s: string, w: number) => {
  const f = clip(s, w)
  const slack = Math.max(0, w - f.length)
  const left = slack >> 1

  return `${' '.repeat(left)}${f}${' '.repeat(slack - left)}`
}

const ruleIn = (label: string, w: number) => {
  const f = clip(label, Math.max(1, w - 4))
  const slack = Math.max(0, w - f.length - 2)
  const left = slack >> 1

  return `${'─'.repeat(left)} ${f} ${'─'.repeat(slack - left)}`
}

function CompactBanner({ cols, t }: { cols: number; t: Theme }) {
  const w = Math.max(28, cols - 4)

  return (
    <Box flexDirection="column" height={3} marginBottom={1} opaque width={w}>
      <Text bold color={t.color.primary}>
        {ruleIn(t.brand.name, w)}
      </Text>
      <Text color={t.color.muted}>{centerIn(TAG_FULL, w)}</Text>
      <Text color={t.color.primary}>{'─'.repeat(w)}</Text>
    </Box>
  )
}

export function Banner({ maxWidth, t }: { maxWidth?: number; t: Theme }) {
  const term = useStdout().stdout?.columns ?? 80
  const cols = Math.max(1, Math.min(term, maxWidth ?? term))

  if (cols < HIDE_BELOW) {
    return null
  }

  const logoLines = logo(t.color, t.bannerLogo || undefined)
  const logoW = t.bannerLogo ? artWidth(logoLines) : LOGO_WIDTH

  if (cols >= logoW + 2) {
    return (
      <Box flexDirection="column" marginBottom={1}>
        <ArtLines lines={logoLines} />
        <Text color={t.color.muted} wrap="truncate-end">
          {t.brand.icon} {TAG_FULL}
        </Text>
      </Box>
    )
  }

  if (cols >= COMPACT_FROM) {
    return <CompactBanner cols={cols} t={t} />
  }

  const name = cols >= 52 ? t.brand.name : t.brand.name.split(' ')[0] ?? t.brand.name
  const tag = cols >= 64 ? TAG_FULL : cols >= 46 ? TAG_MID : TAG_TINY

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text bold color={t.color.primary} wrap="truncate-end">
        {t.brand.icon} {name}
      </Text>
      <Text color={t.color.muted} wrap="truncate-end">
        {t.brand.icon} {tag}
      </Text>
    </Box>
  )
}

// ── SessionPanel (Simplicio Agent — clean layout, no skills/tools/logo) ──

export function SessionPanel({ info, maxWidth, sid, t }: SessionPanelProps) {
  const term = useStdout().stdout?.columns ?? 100
  const cols = Math.max(20, Math.min(term, maxWidth ?? term))
  const w = Math.max(20, cols - 12)

  return (
    <Box borderColor={t.color.border} borderStyle="round" marginBottom={1} paddingX={2} paddingY={1}>
      <Box flexDirection="column" width={w}>
        <Box justifyContent="center" marginBottom={1}>
          <Text bold color={t.color.primary}>
            {t.brand.name}
            {info.version ? ` v${info.version}` : ''}
            {info.release_date ? ` (${info.release_date})` : ''}
          </Text>
        </Box>

        <Text color={t.color.accent} wrap="truncate-end">
          {info.model.split('/').pop()}
        </Text>

        <Text color={t.color.muted} wrap="truncate-end">
          {info.cwd || process.cwd()}
        </Text>

        {sid && (
          <Text wrap="truncate-end">
            <Text color={t.color.sessionLabel}>Session: </Text>
            <Text color={t.color.sessionBorder}>{sid}</Text>
          </Text>
        )}

        {info.install_warning && (
          <Text bold color={t.color.warn} wrap="wrap">
            ! {info.install_warning}
          </Text>
        )}
      </Box>
    </Box>
  )
}

export function Panel({ sections, t, title }: PanelProps) {
  return (
    <Box borderColor={t.color.border} borderStyle="round" flexDirection="column" paddingX={2} paddingY={1}>
      <Box justifyContent="center" marginBottom={1}>
        <Text bold color={t.color.primary}>
          {title}
        </Text>
      </Box>

      {sections.map((sec, si) => (
        <Box flexDirection="column" key={si} marginTop={si > 0 ? 1 : 0}>
          {sec.title && (
            <Text bold color={t.color.accent}>
              {sec.title}
            </Text>
          )}

          {sec.rows?.map(([k, v], ri) => (
            <Text key={ri} wrap="truncate">
              <Text color={t.color.muted}>{k.padEnd(20)}</Text>
              <Text color={t.color.text}>{v}</Text>
            </Text>
          ))}

          {sec.items?.map((item, ii) => (
            <Text color={t.color.text} key={ii} wrap="truncate">
              {item}
            </Text>
          ))}

          {sec.text && <Text color={t.color.muted}>{sec.text}</Text>}
        </Box>
      ))}
    </Box>
  )
}

interface PanelProps {
  sections: PanelSection[]
  t: Theme
  title: string
}

interface SessionPanelProps {
  info: SessionInfo
  maxWidth?: number
  sid?: string | null
  t: Theme
}

import { StatusDot } from '@/components/status-dot'
import type { Translations } from '@/i18n'
import { cn } from '@/lib/utils'

import { EditorMonogram } from './editor-monogram'
import { EDITOR_STATE_TONE, type EditorConnectionState, editorConnectionState } from './editor-presentation'
import type { IntegrationEditorInfo } from './types'

const TONE_CARD_CLASS: Record<EditorConnectionState, string> = {
  connected: 'border-primary/35 bg-primary/[0.04]',
  installed: 'border-amber-500/35 bg-amber-500/[0.04]',
  'not-installed': 'border-(--ui-stroke-secondary) bg-(--ui-bg-secondary)'
}

function stateLabel(state: EditorConnectionState, copy: Translations['integrations']): string {
  if (state === 'connected') {
    return copy.stateConnected
  }

  return state === 'installed' ? copy.stateInstalled : copy.stateNotInstalled
}

interface EditorCardProps {
  editor: IntegrationEditorInfo
  index: number
  entered: boolean
  copy: Translations['integrations']
}

// One card per editor/agent the backend can see. Every visual cue —
// border/background tint, the status dot, and the label — is driven purely by
// `editor.installed` / `editor.registered` as reported this poll; nothing here
// is optimistic or cached across a deploy attempt.
export function EditorCard({ editor, index, entered, copy }: EditorCardProps) {
  const state = editorConnectionState(editor)

  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-[10px] border px-3.5 py-3 duration-300 ease-out',
        'transition-[opacity,transform,box-shadow,background-color,border-color]',
        'hover:-translate-y-0.5 hover:shadow-[0_0_20px_-10px_var(--primary)] motion-reduce:hover:translate-y-0',
        TONE_CARD_CLASS[state],
        entered ? 'translate-y-0 opacity-100' : 'translate-y-1.5 opacity-0',
        'motion-reduce:translate-y-0 motion-reduce:opacity-100 motion-reduce:transition-none'
      )}
      style={{ transitionDelay: entered ? `${Math.min(index * 40, 320)}ms` : '0ms' }}
    >
      <EditorMonogram id={editor.id} name={editor.name} />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium text-foreground">{editor.name}</span>
        </div>
        <div className="mt-1 flex items-center gap-1.5">
          <StatusDot tone={EDITOR_STATE_TONE[state]} />
          <span className="text-xs text-muted-foreground">{stateLabel(state, copy)}</span>
        </div>
        <div
          className="mt-1.5 truncate font-mono text-[0.65rem] text-(--ui-text-quaternary)"
          title={editor.configPath || undefined}
        >
          {editor.configPath || copy.configPathUnknown}
        </div>
      </div>
    </div>
  )
}

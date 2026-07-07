import { cn } from '@/lib/utils'

import { editorAccentClass, editorMonogram } from './editor-presentation'

interface EditorMonogramProps {
  id: string
  name: string
  className?: string
}

// A styled two-letter mark standing in for a per-editor logo — this screen
// never downloads or bundles third-party brand assets, so every editor
// (known or newly reported by the backend) gets a deterministic, readable
// monogram instead.
export function EditorMonogram({ id, name, className }: EditorMonogramProps) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'grid size-9 shrink-0 place-items-center rounded-[8px] text-[0.7rem] font-semibold tracking-tight',
        editorAccentClass(id),
        className
      )}
    >
      {editorMonogram(id, name)}
    </div>
  )
}

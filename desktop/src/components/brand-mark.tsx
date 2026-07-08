import { cn } from '@/lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Brand badge: the official Simplicio mark (green hexagonal "S" on black),
// identical in light/dark. Fills the tile (softly rounded); size via
// className (default size-14). The source PNG already carries its own black
// background, so the tile itself stays black rather than white.
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'inline-flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-md bg-black',
        className
      )}
      {...props}
    >
      <img alt="Simplicio" className="size-full object-contain" src={assetPath('simplicio-logo.png')} />
    </span>
  )
}

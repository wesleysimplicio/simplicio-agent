// Simple mode — hide advanced features for non-technical users.
// Default: ON. Toggle via titlebar button "⚡ Avançado".
import { atom } from 'nanostores'

/** When true, advanced panels are hidden. User sees only chat + voice. */
export const $simpleMode = atom<boolean>(true)

/** Toggle simple/advanced mode. */
export function toggleSimpleMode(): void {
  $simpleMode.set(!$simpleMode.get())
}

import { defineLocale } from './define-locale'

// Malay locale placeholder -- catalog.ts declared this language but no
// translation file backed it (pre-existing gap, not from this change).
// Falls back to English for every string until real translations land.
export const ms = defineLocale({})

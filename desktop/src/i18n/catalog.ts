import { ar } from './ar'
import { en } from './en'
import { es } from './es'
import { fr } from './fr'
import { he } from './he'
import { hi } from './hi'
import { id } from './id'
import { it } from './it'
import { ja } from './ja'
import { ko } from './ko'
import { ms } from './ms'
import { pl } from './pl'
import { ptBr } from './pt-BR'
import { ru } from './ru'
import type { Locale, Translations } from './types'
import { zh } from './zh'
import { zhHant } from './zh-hant'

export const TRANSLATIONS: Record<Locale, Translations> = {
  en,
  zh,
  'zh-hant': zhHant,
  ja,
  ar,
  es,
  fr,
  he,
  hi,
  id,
  it,
  ko,
  ms,
  pl,
  'pt-BR': ptBr,
  ru
}

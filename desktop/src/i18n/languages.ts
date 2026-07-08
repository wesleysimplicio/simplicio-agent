import type { Locale } from './types'

export const DEFAULT_LOCALE: Locale = 'en'

export const LOCALE_OPTIONS = [
  {
    id: 'en',
    name: 'English',
    englishName: 'English',
    configValue: 'en'
  },
  {
    id: 'zh',
    name: '简体中文',
    englishName: 'Simplified Chinese',
    configValue: 'zh'
  },
  {
    id: 'zh-hant',
    name: '繁體中文',
    englishName: 'Traditional Chinese',
    configValue: 'zh-hant'
  },
  {
    id: 'ja',
    name: '日本語',
    englishName: 'Japanese',
    configValue: 'ja'
  },
  {
    id: 'es',
    name: 'Español',
    englishName: 'Spanish',
    configValue: 'es'
  },
  {
    id: 'fr',
    name: 'Français',
    englishName: 'French',
    configValue: 'fr'
  },
  {
    id: 'it',
    name: 'Italiano',
    englishName: 'Italian',
    configValue: 'it'
  },
  {
    id: 'pt-BR',
    name: 'Português (Brasil)',
    englishName: 'Portuguese (Brazil)',
    configValue: 'pt-BR'
  },
  {
    id: 'ru',
    name: 'Русский',
    englishName: 'Russian',
    configValue: 'ru'
  },
  {
    id: 'pl',
    name: 'Polski',
    englishName: 'Polish',
    configValue: 'pl'
  },
  {
    id: 'ko',
    name: '한국어',
    englishName: 'Korean',
    configValue: 'ko'
  },
  {
    id: 'id',
    name: 'Bahasa Indonesia',
    englishName: 'Indonesian',
    configValue: 'id'
  },
  {
    id: 'ms',
    name: 'Bahasa Melayu',
    englishName: 'Malay',
    configValue: 'ms'
  },
  {
    id: 'hi',
    name: 'हिन्दी',
    englishName: 'Hindi',
    configValue: 'hi'
  },
  {
    id: 'ar',
    name: 'العربية',
    englishName: 'Arabic',
    configValue: 'ar'
  },
  {
    id: 'he',
    name: 'עברית',
    englishName: 'Hebrew',
    configValue: 'he'
  }
] as const satisfies readonly { configValue: string; englishName: string; id: Locale; name: string }[]

// `name` is the endonym (native name) shown in the picker so users recognize
// their language regardless of the current UI language. No country flags:
// languages are not countries. `englishName` is search-only (not shown) so an
// English speaker can type "japanese"/"traditional" to filter the list.
export const LOCALE_META: Record<Locale, { name: string; englishName: string }> = Object.fromEntries(
  LOCALE_OPTIONS.map(locale => [locale.id, { name: locale.name, englishName: locale.englishName }])
) as Record<Locale, { name: string; englishName: string }>

const LOCALE_ALIASES: Record<string, Locale> = {
  en: 'en',
  'en-us': 'en',
  en_us: 'en',
  zh: 'zh',
  'zh-cn': 'zh',
  zh_cn: 'zh',
  'zh-hans': 'zh',
  zh_hans: 'zh',
  'zh-hans-cn': 'zh',
  zh_hans_cn: 'zh',
  'zh-tw': 'zh-hant',
  zh_tw: 'zh-hant',
  'zh-hk': 'zh-hant',
  zh_hk: 'zh-hant',
  'zh-mo': 'zh-hant',
  zh_mo: 'zh-hant',
  'zh-hant': 'zh-hant',
  zh_hant: 'zh-hant',
  'zh-hant-tw': 'zh-hant',
  zh_hant_tw: 'zh-hant',
  'zh-hant-hk': 'zh-hant',
  zh_hant_hk: 'zh-hant',
  ja: 'ja',
  'ja-jp': 'ja',
  ja_jp: 'ja',
  es: 'es',
  'es-es': 'es',
  es_es: 'es',
  'es-mx': 'es',
  es_mx: 'es',
  'es-419': 'es',
  es_419: 'es',
  fr: 'fr',
  'fr-fr': 'fr',
  fr_fr: 'fr',
  'fr-ca': 'fr',
  fr_ca: 'fr',
  it: 'it',
  'it-it': 'it',
  it_it: 'it',
  pt: 'pt-BR',
  'pt-br': 'pt-BR',
  pt_br: 'pt-BR',
  'pt-pt': 'pt-BR',
  pt_pt: 'pt-BR',
  ru: 'ru',
  'ru-ru': 'ru',
  ru_ru: 'ru',
  pl: 'pl',
  'pl-pl': 'pl',
  pl_pl: 'pl',
  ko: 'ko',
  'ko-kr': 'ko',
  ko_kr: 'ko',
  id: 'id',
  'id-id': 'id',
  id_id: 'id',
  in: 'id',
  ms: 'ms',
  'ms-my': 'ms',
  ms_my: 'ms',
  hi: 'hi',
  'hi-in': 'hi',
  hi_in: 'hi',
  ar: 'ar',
  'ar-sa': 'ar',
  ar_sa: 'ar',
  he: 'he',
  'he-il': 'he',
  he_il: 'he',
  iw: 'he'
}

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && LOCALE_OPTIONS.some(locale => locale.id === value)
}

export function normalizeLocale(value: unknown): Locale {
  if (typeof value !== 'string') {
    return DEFAULT_LOCALE
  }

  return LOCALE_ALIASES[value.trim().toLowerCase()] ?? DEFAULT_LOCALE
}

export function isSupportedLocaleValue(value: unknown): boolean {
  return typeof value === 'string' && LOCALE_ALIASES[value.trim().toLowerCase()] != null
}

export function localeConfigValue(locale: Locale): string {
  return LOCALE_OPTIONS.find(item => item.id === locale)?.configValue ?? DEFAULT_LOCALE
}

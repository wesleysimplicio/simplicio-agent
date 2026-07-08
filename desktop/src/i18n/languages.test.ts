import { describe, expect, it } from 'vitest'

import { DEFAULT_LOCALE, isLocale, isSupportedLocaleValue, localeConfigValue, normalizeLocale } from './languages'

describe('desktop i18n languages', () => {
  it('normalizes supported locale aliases', () => {
    expect(normalizeLocale('en')).toBe('en')
    expect(normalizeLocale('EN-US')).toBe('en')
    expect(normalizeLocale('zh')).toBe('zh')
    expect(normalizeLocale('zh-CN')).toBe('zh')
    expect(normalizeLocale('zh-Hans')).toBe('zh')
    expect(normalizeLocale(' zh_hans_cn ')).toBe('zh')
    expect(normalizeLocale('zh-Hant')).toBe('zh-hant')
    expect(normalizeLocale('zh-TW')).toBe('zh-hant')
    expect(normalizeLocale('zh_HK')).toBe('zh-hant')
    expect(normalizeLocale('ja')).toBe('ja')
    expect(normalizeLocale('ja-JP')).toBe('ja')
    expect(normalizeLocale('es')).toBe('es')
    expect(normalizeLocale('es-MX')).toBe('es')
    expect(normalizeLocale('fr-CA')).toBe('fr')
    expect(normalizeLocale('pt')).toBe('pt-BR')
    expect(normalizeLocale('pt-PT')).toBe('pt-BR')
    expect(normalizeLocale('ru-RU')).toBe('ru')
    expect(normalizeLocale('pl')).toBe('pl')
    expect(normalizeLocale('ko-KR')).toBe('ko')
    expect(normalizeLocale('id')).toBe('id')
    expect(normalizeLocale('IN')).toBe('id')
    expect(normalizeLocale('ms-MY')).toBe('ms')
    expect(normalizeLocale('hi-IN')).toBe('hi')
    expect(normalizeLocale('ar-SA')).toBe('ar')
    expect(normalizeLocale('he-IL')).toBe('he')
    expect(normalizeLocale('iw')).toBe('he')
  })

  it('falls back to English for empty or unsupported values', () => {
    expect(normalizeLocale(null)).toBe(DEFAULT_LOCALE)
    expect(normalizeLocale('')).toBe(DEFAULT_LOCALE)
    expect(normalizeLocale('de')).toBe(DEFAULT_LOCALE)
  })

  it('distinguishes exact locale ids from supported config aliases', () => {
    expect(isSupportedLocaleValue('zh-CN')).toBe(true)
    expect(isSupportedLocaleValue('zh-TW')).toBe(true)
    expect(isSupportedLocaleValue('ja-JP')).toBe(true)
    expect(isSupportedLocaleValue('de')).toBe(false)
    expect(isLocale('zh-CN')).toBe(false)
    expect(isLocale('zh')).toBe(true)
    expect(isLocale('zh-hant')).toBe(true)
    expect(isLocale('ja')).toBe(true)
    expect(isLocale('pt-BR')).toBe(true)
    expect(isLocale('pt')).toBe(false)
  })

  it('returns the persisted config value for supported locales', () => {
    expect(localeConfigValue('en')).toBe('en')
    expect(localeConfigValue('zh')).toBe('zh')
    expect(localeConfigValue('zh-hant')).toBe('zh-hant')
    expect(localeConfigValue('ja')).toBe('ja')
    expect(localeConfigValue('pt-BR')).toBe('pt-BR')
    expect(localeConfigValue('ar')).toBe('ar')
  })
})

import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'

import { en } from './en'
import { pl } from './pl'

export const LANGUAGES = { en: 'English', pl: 'Polski' } as const
export type Language = keyof typeof LANGUAGES

declare module 'i18next' {
  interface CustomTypeOptions {
    resources: { translation: typeof en }
  }
}

/** English unless the browser (or an earlier choice) prefers Polish. */
export function initI18n(language?: Language): typeof i18n {
  if (!i18n.isInitialized) {
    void i18n
      .use(LanguageDetector)
      .use(initReactI18next)
      .init({
        resources: { en: { translation: en }, pl: { translation: pl } },
        supportedLngs: Object.keys(LANGUAGES),
        nonExplicitSupportedLngs: true,
        fallbackLng: 'en',
        interpolation: { escapeValue: false }, // React escapes
        detection: { order: ['localStorage', 'navigator'], caches: ['localStorage'] },
        ...(language === undefined ? {} : { lng: language }),
      })
  } else if (language !== undefined) {
    void i18n.changeLanguage(language)
  }
  return i18n
}

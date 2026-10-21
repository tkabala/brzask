import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { RouterProvider, type RouterHistory } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { I18nextProvider } from 'react-i18next'

import { initI18n } from '@/i18n'
import { createAppRouter } from '@/router'

/** The whole app; tests render it with their own query client and history. */
export function App({
  queryClient,
  history,
}: {
  queryClient: QueryClient
  history?: RouterHistory
}) {
  const [router] = useState(() => createAppRouter(queryClient, history))
  const [i18n] = useState(() => initI18n())

  useEffect(() => {
    const setLang = (language: string) => {
      document.documentElement.lang = language
    }
    setLang(i18n.resolvedLanguage ?? 'en')
    i18n.on('languageChanged', setLang)
    return () => {
      i18n.off('languageChanged', setLang)
    }
  }, [i18n])

  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </I18nextProvider>
  )
}

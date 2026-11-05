import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { type Persister, PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { RouterProvider, type RouterHistory } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { I18nextProvider } from 'react-i18next'

import { initI18n } from '@/i18n'
import { persistOptions } from '@/lib/offline-cache'
import { createAppRouter } from '@/router'

/** The whole app; tests render it with their own query client and history.
 * With a persister, today's digest stays readable offline. */
export function App({
  queryClient,
  history,
  persister,
}: {
  queryClient: QueryClient
  history?: RouterHistory
  persister?: Persister
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

  const app = <RouterProvider router={router} />
  return (
    <I18nextProvider i18n={i18n}>
      {persister ? (
        <PersistQueryClientProvider
          client={queryClient}
          persistOptions={persistOptions(persister)}
          // The copy may be seconds old and still wrong (a logout elsewhere): ask again.
          onSuccess={() => void queryClient.invalidateQueries()}
        >
          {app}
        </PersistQueryClientProvider>
      ) : (
        <QueryClientProvider client={queryClient}>{app}</QueryClientProvider>
      )}
    </I18nextProvider>
  )
}

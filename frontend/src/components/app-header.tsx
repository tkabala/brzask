import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { logoutMutation } from '@/client/@tanstack/react-query.gen'
import type { SessionOut } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { LANGUAGES } from '@/i18n'
import { setCsrfToken } from '@/lib/api'
import { forgetSaved } from '@/lib/offline-cache'
import { chooseTheme, type Theme, THEMES, useTheme } from '@/lib/theme'

const NAV = [
  ['/', 'today'],
  ['/archive', 'archive'],
  ['/search', 'search'],
  ['/sources', 'sources'],
  ['/interests', 'interests'],
  ['/status', 'status'],
] as const

export function AppHeader({ session }: { session: SessionOut }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const theme = useTheme()
  const logout = useMutation({
    ...logoutMutation(),
    // Offline the request fails at once instead of waiting: the saved copy
    // must go now, not whenever the connection returns.
    networkMode: 'always',
    onMutate: () => {
      forgetSaved(queryClient)
    },
    onSettled: () => {
      setCsrfToken(null)
      forgetSaved(queryClient)
      // Back to nothing known: the session is asked again, and the gate shows the login.
      void queryClient.resetQueries()
    },
  })

  return (
    <header className="border-b">
      <div className="mx-auto flex max-w-2xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <span className="font-semibold tracking-tight">{t('app.name')}</span>
        <nav className="flex flex-wrap gap-3 text-sm">
          {NAV.map(([to, key]) => (
            <Link
              key={to}
              to={to}
              activeOptions={{ exact: to === '/' }}
              className="text-muted-foreground [&.active]:text-foreground"
            >
              {t(`app.nav.${key}`)}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <label className="sr-only" htmlFor="language">
            {t('app.language')}
          </label>
          <select
            id="language"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={i18n.resolvedLanguage ?? 'en'}
            onChange={(event) => void i18n.changeLanguage(event.target.value)}
          >
            {Object.entries(LANGUAGES).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="theme">
            {t('app.theme.label')}
          </label>
          <select
            id="theme"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={theme}
            onChange={(event) => {
              chooseTheme(event.target.value as Theme)
            }}
          >
            {THEMES.map((value) => (
              <option key={value} value={value}>
                {t(`app.theme.${value}`)}
              </option>
            ))}
          </select>
          {session.mode === 'password' ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={logout.isPending}
              onClick={() => {
                logout.mutate({})
              }}
            >
              {t('app.logout')}
            </Button>
          ) : null}
        </div>
      </div>
    </header>
  )
}

import { useTranslation } from 'react-i18next'

import { signInUrl } from '@/lib/base'

/** Shown when the server answered with something other than brzask, which
 * is what an expired login at a proxy looks like to the app. */
export function SignInAgain() {
  const { t } = useTranslation()
  return (
    <a href={signInUrl()} className="text-sm font-medium underline underline-offset-4">
      {t('offline.signIn')}
    </a>
  )
}

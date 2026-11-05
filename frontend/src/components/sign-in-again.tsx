import { useTranslation } from 'react-i18next'

/** The address that skips the saved app: `?signin` is never answered by the
 * service worker, so a proxy in front of brzask sees the visit and can ask
 * for its login again (`src/lib/sw-routes.ts`). */
export const SIGN_IN_URL = '/?signin'

/** Shown when the server answered with something other than brzask, which
 * is what an expired login at a proxy looks like to the app. */
export function SignInAgain() {
  const { t } = useTranslation()
  return (
    <a href={SIGN_IN_URL} className="text-sm font-medium underline underline-offset-4">
      {t('offline.signIn')}
    </a>
  )
}

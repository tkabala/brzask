import { WifiOff } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { useOnline } from '@/lib/online'

/** Said once at the top while offline: what still works and what does not. */
export function OfflineBanner() {
  const { t } = useTranslation()
  const online = useOnline()
  if (online) return null
  return (
    <div role="status" className="border-b bg-muted text-sm text-muted-foreground">
      <p className="mx-auto flex max-w-2xl items-center gap-2 px-4 py-2">
        <WifiOff className="size-4 shrink-0" aria-hidden />
        {t('offline.banner')}
      </p>
    </div>
  )
}

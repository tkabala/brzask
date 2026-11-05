import type { FetchStatus } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

/** What a page shows before its data arrives: nothing, or, when the query
 * waits for a connection, that it needs one. */
export function Pending({ query }: { query: { fetchStatus: FetchStatus } }) {
  const { t } = useTranslation()
  if (query.fetchStatus !== 'paused') return null
  return <p className="text-muted-foreground">{t('offline.page')}</p>
}

import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { getTodayDigestOptions } from '@/client/@tanstack/react-query.gen'
import { DigestPage } from '@/features/digest/digest-page'

export const Route = createFileRoute('/')({
  component: TodayPage,
})

function TodayPage() {
  const { t } = useTranslation()
  // Fetched here, not in a route loader: loaders run before the session gate
  // knows whether the reader is logged in.
  const options = getTodayDigestOptions()
  const digest = useQuery(options)
  return (
    <DigestPage
      digest={digest}
      queryKey={options.queryKey}
      title={t('today.title')}
      empty={
        <>
          <p>{t('today.empty')}</p>
          <p className="mt-1 text-sm">{t('today.emptyHint')}</p>
        </>
      }
    />
  )
}

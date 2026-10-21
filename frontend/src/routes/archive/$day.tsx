import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { getDigestOptions } from '@/client/@tanstack/react-query.gen'
import { DigestPage } from '@/features/digest/digest-page'
import { formatDay } from '@/lib/format'

export const Route = createFileRoute('/archive/$day')({
  component: DayPage,
})

function DayPage() {
  const { day } = Route.useParams()
  const { t, i18n } = useTranslation()
  const options = getDigestOptions({ path: { day } })
  const digest = useQuery(options)
  return (
    <>
      <Link to="/archive" className="text-sm text-muted-foreground hover:underline">
        ← {t('archive.back')}
      </Link>
      <div className="mt-2">
        <DigestPage
          digest={digest}
          queryKey={options.queryKey}
          title={t('archive.day', { day: formatDay(day, i18n.resolvedLanguage ?? 'en') })}
          empty={<p>{t('archive.dayEmpty')}</p>}
        />
      </div>
    </>
  )
}

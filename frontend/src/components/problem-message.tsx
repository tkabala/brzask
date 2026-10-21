import { CircleAlert } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ApiProblem } from '@/lib/api'

/** An error as the reader sees it: the problem's own words, or a plain explanation. */
export function ProblemMessage({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation()
  const [title, detail] =
    error instanceof ApiProblem
      ? [error.problem.title, error.problem.detail]
      : [t('problem.title'), t('problem.offline')]
  return (
    <Alert variant="destructive" role="alert">
      <CircleAlert />
      <AlertTitle>{title}</AlertTitle>
      {detail ? <AlertDescription>{detail}</AlertDescription> : null}
      {onRetry ? (
        <Button variant="outline" size="sm" className="mt-3 w-fit" onClick={onRetry}>
          {t('problem.retry')}
        </Button>
      ) : null}
    </Alert>
  )
}

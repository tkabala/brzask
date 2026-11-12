import { useTranslation } from 'react-i18next'

import type { ChangeOut } from '@/client/types.gen'
import { ProblemMessage } from '@/components/problem-message'
import { Button } from '@/components/ui/button'
import { formatMoment } from '@/lib/format'

import { actionKey, agentName, changedFields } from './describe'

interface Props {
  changes: ChangeOut[]
  onApprove: (change: ChangeOut) => void
  onReject: (change: ChangeOut) => void
  busyId?: number | null
  /** What the server answered when deciding a change failed, by change ID. */
  errors?: Record<number, unknown>
}

export function ChangesView({ changes, onApprove, onReject, busyId = null, errors = {} }: Props) {
  const { t } = useTranslation()
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{t('changes.title')}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t('changes.hint')}</p>
      {changes.length === 0 ? (
        <p className="mt-4 text-muted-foreground">{t('changes.empty')}</p>
      ) : (
        <ul className="mt-2 divide-y">
          {changes.map((change) => (
            <li key={change.id}>
              <ChangeItem
                change={change}
                busy={busyId === change.id}
                error={errors[change.id]}
                onApprove={onApprove}
                onReject={onReject}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

interface ItemProps {
  change: ChangeOut
  busy: boolean
  error: unknown
  onApprove: (change: ChangeOut) => void
  onReject: (change: ChangeOut) => void
}

// Everything shown here comes from an agent: plain text only, never a link or markup.
function ChangeItem({ change, busy, error, onApprove, onReject }: ItemProps) {
  const { t, i18n } = useTranslation()
  const key = actionKey(change.action)
  const entity = change.entity ?? change.entity_id ?? ''
  const title = key ? t(`changes.action.${key}`, { entity }) : `${change.action} ${entity}`
  const titleId = `change-${String(change.id)}`

  return (
    <article className="grid gap-2 py-3" aria-labelledby={titleId}>
      <h3 id={titleId} className="font-medium">
        {title}
      </h3>
      <p className="text-xs text-muted-foreground">
        {t('changes.by')} <span className="font-medium">{agentName(change.actor)}</span>
        {' · '}
        {formatMoment(change.created_at, i18n.resolvedLanguage ?? 'en')}
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {changedFields(change).map((field) => (
          <div key={field.name} className="contents">
            <dt className="text-muted-foreground">{field.name}</dt>
            <dd className="break-words">
              <span className="text-muted-foreground line-through">{field.before}</span>
              {' → '}
              <span>{field.after}</span>
            </dd>
          </div>
        ))}
      </dl>
      {change.reason ? (
        <p className="text-sm">
          <span className="text-muted-foreground">{t('changes.reason')}: </span>
          {change.reason}
        </p>
      ) : null}
      {error ? <ProblemMessage error={error} /> : null}
      <div className="mt-1 flex gap-2">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => {
            onApprove(change)
          }}
        >
          {t('changes.approve')}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => {
            onReject(change)
          }}
        >
          {t('changes.reject')}
        </Button>
      </div>
    </article>
  )
}

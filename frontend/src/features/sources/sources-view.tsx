import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { SourceOut } from '@/client/types.gen'
import { Button } from '@/components/ui/button'

import { type Filter, FILTERS } from './filters'
import { type Decision, SourceItem } from './source-item'

interface Props {
  pending: SourceOut[]
  sources: SourceOut[]
  filter: Filter
  onFilter: (filter: Filter) => void
  hasMore: boolean
  onMore?: () => void
  onDecide?: (source: SourceOut, status: Decision) => void
  busyId?: number | null
  addForm?: ReactNode
}

export function SourcesView({
  pending,
  sources,
  filter,
  onFilter,
  hasMore,
  onMore,
  onDecide,
  busyId = null,
  addForm,
}: Props) {
  const { t } = useTranslation()
  const item = (source: SourceOut) => (
    <li key={source.id}>
      <SourceItem source={source} busy={busyId === source.id} {...(onDecide ? { onDecide } : {})} />
    </li>
  )

  return (
    <div className="grid gap-10">
      <h1 className="text-2xl font-semibold tracking-tight">{t('sources.title')}</h1>
      {pending.length > 0 ? (
        <section aria-labelledby="pending-title">
          <h2 id="pending-title" className="text-lg font-semibold">
            {t('sources.pending')}
          </h2>
          <p className="text-sm text-muted-foreground">{t('sources.pendingHint')}</p>
          <ul className="mt-2 divide-y">{pending.map(item)}</ul>
        </section>
      ) : null}
      {addForm ? <section>{addForm}</section> : null}
      <section aria-labelledby="all-title">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="all-title" className="text-lg font-semibold">
            {t('sources.all')}
          </h2>
          <label className="flex items-center gap-2 text-sm">
            {t('sources.filter')}
            <select
              className="rounded-md border bg-background px-2 py-1"
              value={filter}
              onChange={(event) => {
                onFilter(event.target.value as Filter)
              }}
            >
              {FILTERS.map((value) => (
                <option key={value} value={value}>
                  {value === 'all' ? t('sources.filterAll') : t(`sources.status.${value}`)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {sources.length === 0 ? (
          <p className="mt-2 text-muted-foreground">{t('sources.empty')}</p>
        ) : (
          <ul className="mt-2 divide-y">{sources.map(item)}</ul>
        )}
        {hasMore ? (
          <Button variant="outline" className="mt-4" onClick={onMore}>
            {t('app.loadMore')}
          </Button>
        ) : null}
      </section>
    </div>
  )
}

import { Check } from 'lucide-react'
import { type ReactNode, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ArticleOut } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'

interface Props {
  article: ArticleOut
  /** Called when the reader follows the link, to mark it opened at once. */
  onOpen?: (article: ArticleOut) => void
  /** The "why here?" content, rendered only once asked for. */
  renderWhy?: () => ReactNode
}

/** One article of a digest: its link goes through `open_url`, which records the open. */
export function ArticleCard({ article, onOpen, renderWhy }: Props) {
  const { t } = useTranslation()
  const [showWhy, setShowWhy] = useState(false)
  const whyId = useId()
  const opened = article.opened_at !== null
  const open = () => onOpen?.(article)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-baseline gap-3">
          {article.position !== null ? (
            <span className="font-mono text-sm text-muted-foreground">{article.position}</span>
          ) : null}
          <div className="min-w-0 flex-1">
            <h2 className="text-lg leading-snug font-semibold">
              <a
                href={article.open_url}
                target="_blank"
                rel="noopener"
                className="hover:underline"
                onClick={open}
                onAuxClick={open}
              >
                {article.title}
              </a>
            </h2>
            <p className="mt-1 flex flex-wrap gap-x-2 text-sm text-muted-foreground">
              {article.source ? <span>{article.source.name}</span> : null}
              {article.topic ? <span>· {article.topic}</span> : null}
              {opened ? (
                <span className="inline-flex items-center gap-1 text-foreground">
                  · <Check className="size-3.5" aria-hidden />
                  <span>{t('article.opened')}</span>
                </span>
              ) : null}
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm">
        {article.summary ? <p>{article.summary}</p> : null}
        {article.why_it_matters ? (
          <p className="text-muted-foreground">
            <span className="font-medium text-foreground">{t('article.whyItMatters')}: </span>
            {article.why_it_matters}
          </p>
        ) : null}
        {renderWhy ? (
          <div>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0"
              aria-expanded={showWhy}
              aria-controls={whyId}
              onClick={() => {
                setShowWhy((shown) => !shown)
              }}
            >
              {showWhy ? t('article.hideWhy') : t('article.whyHere')}
            </Button>
            {showWhy ? (
              <div id={whyId} className="mt-2">
                {renderWhy()}
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

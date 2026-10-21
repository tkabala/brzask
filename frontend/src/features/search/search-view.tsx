import { type SubmitEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ArticleOut, SearchResults } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ArticleCard } from '@/features/digest/article-card'

interface Props {
  query: string
  /** Null before the first search, or while one runs. */
  results: SearchResults | null
  onSearch: (query: string) => void
  onOpen?: (article: ArticleOut) => void
}

export function SearchView({ query, results, onSearch, onOpen }: Props) {
  const { t } = useTranslation()
  const [text, setText] = useState(query)
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (text.trim()) onSearch(text.trim())
  }

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{t('search.title')}</h1>
      <form className="mt-4 grid gap-2" role="search" onSubmit={submit}>
        <Label htmlFor="search">{t('search.label')}</Label>
        <div className="flex gap-2">
          <Input
            id="search"
            type="search"
            value={text}
            maxLength={500}
            placeholder={t('search.placeholder')}
            onChange={(event) => {
              setText(event.target.value)
            }}
          />
          <Button type="submit">{t('search.submit')}</Button>
        </div>
        <p className="text-sm text-muted-foreground">{t('search.hint')}</p>
      </form>
      {results === null ? null : results.items.length === 0 ? (
        <p className="mt-6 text-muted-foreground">{t('search.empty')}</p>
      ) : (
        <ol className="mt-6 grid gap-4">
          {results.items.map((hit) => (
            <li key={hit.article.id}>
              <p className="mb-1 text-xs text-muted-foreground">
                {t('search.similarity', { percent: Math.round(hit.similarity * 100) })}
              </p>
              <ArticleCard article={hit.article} {...(onOpen ? { onOpen } : {})} />
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

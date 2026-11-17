import { Link, useCanGoBack, useRouter } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import type { ArticleOut, BriefOut } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { formatOffset } from '@/lib/format'

/** Back where the reader came from, or to today's digest on a fresh visit. */
function BackToDigest() {
  const { t } = useTranslation()
  const router = useRouter()
  const canGoBack = useCanGoBack()
  return (
    <Link
      to="/"
      className="text-sm text-muted-foreground hover:underline"
      onClick={(event) => {
        if (!canGoBack) return
        event.preventDefault()
        router.history.back()
      }}
    >
      ← {t('brief.back')}
    </Link>
  )
}

function ArticleHeading({ article }: { article: ArticleOut }) {
  return (
    <>
      <h1 className="mt-3 text-2xl leading-tight font-semibold tracking-tight">{article.title}</h1>
      <p className="mt-1 flex flex-wrap gap-x-2 text-sm text-muted-foreground">
        {article.source ? <span>{article.source.name}</span> : null}
        {article.topic ? <span>· {article.topic}</span> : null}
      </p>
    </>
  )
}

/** The way to the original, through `open_url`; it stays at the bottom of the screen. */
function OpenOriginal({ article, onOpen }: { article: ArticleOut; onOpen?: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="sticky bottom-0 mt-8 bg-background pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <Button asChild size="lg" className="h-11 w-full text-base">
        <a href={article.open_url} target="_blank" rel="noopener" onClick={onOpen}>
          {t('brief.openOriginal')}
        </a>
      </Button>
    </div>
  )
}

interface Props {
  brief: BriefOut
  /** Called when the reader follows the original or a chapter. */
  onOpen?: (article: ArticleOut) => void
}

/** What an article says, read in the app: gist, points, caveats and chapters. */
export function BriefView({ brief, onOpen }: Props) {
  const { t } = useTranslation()
  const { article } = brief
  const open = () => onOpen?.(article)
  return (
    <article className="mx-auto max-w-prose">
      <BackToDigest />
      <ArticleHeading article={article} />
      <p className="mt-1 text-sm text-muted-foreground">{t(`brief.basis.${brief.basis}`)}</p>
      <p className="mt-5 text-lg leading-relaxed">{brief.gist}</p>
      {brief.points.length > 0 ? (
        <ul className="mt-4 grid list-disc gap-2 pl-5 leading-relaxed">
          {brief.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      ) : null}
      {brief.caveats.length > 0 ? (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-muted-foreground">{t('brief.caveats')}</h2>
          <ul className="mt-2 grid list-disc gap-1 pl-5 text-sm leading-relaxed">
            {brief.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {brief.chapters.length > 0 ? (
        <section className="mt-6">
          <h2 className="text-sm font-medium text-muted-foreground">{t('brief.chapters')}</h2>
          <ol className="mt-2 grid gap-1">
            {brief.chapters.map((chapter) => (
              <li key={chapter.start}>
                <a
                  href={chapter.open_url}
                  target="_blank"
                  rel="noopener"
                  className="inline-flex items-baseline gap-2 py-1 hover:underline"
                  onClick={open}
                >
                  <span className="font-mono text-sm text-muted-foreground tabular-nums">
                    {formatOffset(chapter.start)}
                  </span>
                  <span>{chapter.title}</span>
                </a>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <OpenOriginal article={article} onOpen={open} />
    </article>
  )
}

/** No brief (not written yet, or the article is gone): the original, when known. */
export function BriefMissing({
  article,
  onOpen,
}: {
  article: ArticleOut | null
  onOpen?: (article: ArticleOut) => void
}) {
  const { t } = useTranslation()
  return (
    <article className="mx-auto max-w-prose">
      <BackToDigest />
      {article ? <ArticleHeading article={article} /> : null}
      <p className="mt-5 text-muted-foreground">{t('brief.missing')}</p>
      {article ? <OpenOriginal article={article} onOpen={() => onOpen?.(article)} /> : null}
    </article>
  )
}

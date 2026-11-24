import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { canCopy } from '@/lib/clipboard'

async function fetchMarkdown(url: string): Promise<string> {
  const response = await fetch(url, { credentials: 'same-origin' })
  if (!response.ok) throw new Error(`markdown export answered ${String(response.status)}`)
  return response.text()
}

/** Share, copy and download the Markdown served at `url`. `version` changes
 * when the content does, so a grown conversation is fetched again. */
export function ExportButtons({ url, version = '' }: { url: string; version?: string }) {
  const { t } = useTranslation()
  const [note, setNote] = useState<string | null>(null)
  const canShare = typeof navigator !== 'undefined' && 'share' in navigator
  // Fetched ahead, so share and copy run while the click still counts as the
  // reader's gesture (Safari refuses both once a request was awaited).
  const markdown = useQuery({
    queryKey: ['markdown', url, version],
    queryFn: () => fetchMarkdown(url),
    staleTime: Infinity,
  })
  const withMarkdown = (send: (text: string) => Promise<unknown>, done?: string) => {
    const run = markdown.data !== undefined ? send(markdown.data) : fetchMarkdown(url).then(send)
    run.then(
      () => {
        if (done) setNote(done)
      },
      (error: unknown) => {
        // Closing the share sheet is not a failure.
        if (error instanceof DOMException && error.name === 'AbortError') return
        setNote(t('export.failed'))
      },
    )
  }
  return (
    <div className="mt-8 flex flex-wrap gap-2">
      {canShare ? (
        <Button
          variant="outline"
          onClick={() => {
            withMarkdown((text) => navigator.share({ text }))
          }}
        >
          {t('export.share')}
        </Button>
      ) : null}
      {canCopy() ? (
        <Button
          variant="outline"
          onClick={() => {
            withMarkdown((text) => navigator.clipboard.writeText(text), t('export.copied'))
          }}
        >
          {t('export.copy')}
        </Button>
      ) : null}
      <Button variant="outline" asChild>
        <a href={url} download>
          {t('export.download')}
        </a>
      </Button>
      {note ? (
        <span role="status" className="self-center text-sm text-muted-foreground">
          {note}
        </span>
      ) : null}
    </div>
  )
}

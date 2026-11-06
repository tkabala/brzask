import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { OpmlReport } from '@/client/types.gen'
import { ProblemMessage } from '@/components/problem-message'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

export interface OpmlImportValues {
  opml: string
  active: boolean
}

interface Props {
  onImport: (values: OpmlImportValues) => Promise<unknown>
  onExport: () => Promise<unknown>
  importing?: boolean
  exporting?: boolean
  error?: unknown
  report?: OpmlReport | null
}

/** The file's text in the encoding its byte order mark or XML declaration names; else UTF-8. */
async function readOpml(file: File): Promise<string> {
  const bytes = await file.arrayBuffer()
  const [first, second] = new Uint8Array(bytes)
  if (first === 0xff && second === 0xfe) return new TextDecoder('utf-16le').decode(bytes)
  if (first === 0xfe && second === 0xff) return new TextDecoder('utf-16be').decode(bytes)
  const start = new TextDecoder('latin1').decode(bytes.slice(0, 200))
  const encoding = /^\s*<\?xml[^>]*\bencoding=["']([\w.-]+)["']/.exec(start)?.[1] ?? 'utf-8'
  try {
    return new TextDecoder(encoding).decode(bytes)
  } catch {
    return new TextDecoder().decode(bytes) // An encoding the browser does not know.
  }
}

/** OPML in and out: the subscription list every feed reader can export and read. */
export function OpmlForm({
  onImport,
  onExport,
  importing = false,
  exporting = false,
  error = null,
  report = null,
}: Props) {
  const { t } = useTranslation()
  const id = useId()
  const [file, setFile] = useState<File | null>(null)
  const [active, setActive] = useState(false)

  return (
    <div className="grid gap-3">
      <h2 className="text-lg font-semibold">{t('sources.opml.title')}</h2>
      <p className="text-sm text-muted-foreground">{t('sources.opml.hint')}</p>
      <form
        className="grid gap-3"
        aria-label={t('sources.opml.import')}
        onSubmit={(event) => {
          event.preventDefault()
          if (!file) return
          void readOpml(file)
            .then((opml) => onImport({ opml, active }))
            .catch(() => {
              // Shown through `error`; the reader may pick another file.
            })
        }}
      >
        <div className="grid gap-2">
          <Label htmlFor={`${id}-file`}>{t('sources.opml.file')}</Label>
          <input
            id={`${id}-file`}
            type="file"
            accept=".opml,.xml,text/x-opml,text/xml,application/xml"
            className="text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-background file:px-3 file:py-1"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
            }}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(event) => {
              setActive(event.target.checked)
            }}
          />
          {t('sources.opml.active')}
        </label>
        {error ? <ProblemMessage error={error} /> : null}
        {report && !error ? <ImportResult report={report} /> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={!file || importing}>
            {importing ? t('sources.opml.importing') : t('sources.opml.import')}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={exporting}
            onClick={() => void onExport()}
          >
            {t('sources.opml.export')}
          </Button>
        </div>
      </form>
    </div>
  )
}

function ImportResult({ report }: { report: OpmlReport }) {
  const { t } = useTranslation()
  return (
    <div role="status" className="grid gap-1 text-sm">
      <p>
        {t('sources.opml.result', {
          added: report.added.length,
          known: report.known.length,
          failed: report.failed.length,
        })}
      </p>
      {report.unchecked.length > 0 ? (
        <p>{t('sources.opml.unchecked', { number: report.unchecked.length })}</p>
      ) : null}
      {report.failed.length > 0 ? (
        <details>
          <summary className="cursor-pointer">{t('sources.opml.failedList')}</summary>
          <ul className="mt-1 grid gap-1 break-all text-muted-foreground">
            {report.failed.map((failed) => (
              <li key={failed.url}>
                {failed.url}: {failed.reason}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  )
}

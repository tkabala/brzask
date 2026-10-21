import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { z } from 'zod'

import { ProblemMessage } from '@/components/problem-message'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const schema = z.object({ url: z.string().trim().min(1), name: z.string().trim() })
export type NewSourceValues = z.infer<typeof schema>

interface Props {
  onAdd: (values: NewSourceValues) => Promise<unknown>
  pending?: boolean
  error?: unknown
  addedName?: string | null
}

/** Any page of a site will do: the server finds its feed. */
export function AddSourceForm({ onAdd, pending = false, error = null, addedName = null }: Props) {
  const { t } = useTranslation()
  const form = useForm<NewSourceValues>({
    resolver: zodResolver(schema),
    defaultValues: { url: '', name: '' },
  })
  return (
    <form
      className="grid gap-3"
      noValidate
      aria-label={t('sources.add')}
      onSubmit={(event) =>
        void form.handleSubmit(async (values) => {
          try {
            await onAdd(values)
            form.reset()
          } catch {
            // Shown through `error`; the reader may correct the URL and retry.
          }
        })(event)
      }
    >
      <h2 className="text-lg font-semibold">{t('sources.add')}</h2>
      <div className="grid gap-2">
        <Label htmlFor="source-url">{t('sources.addUrl')}</Label>
        <Input
          id="source-url"
          inputMode="url"
          placeholder="https://"
          aria-invalid={form.formState.errors.url ? true : undefined}
          {...form.register('url')}
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="source-name">{t('sources.addName')}</Label>
        <Input id="source-name" {...form.register('name')} />
      </div>
      {error ? <ProblemMessage error={error} /> : null}
      {addedName && !error ? (
        <p role="status" className="text-sm">
          {t('sources.added', { name: addedName })}
        </p>
      ) : null}
      <Button type="submit" className="w-fit" disabled={pending}>
        {pending ? t('sources.adding') : t('sources.addSubmit')}
      </Button>
    </form>
  )
}

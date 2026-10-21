import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'

import type { InterestChange, InterestOut, NewInterest } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

import { interestSchema, type InterestValues, splitKeywords } from './interest-form'
import { InterestItem } from './interest-item'

interface Props {
  interests: InterestOut[]
  onChange: (interest: InterestOut, change: InterestChange) => Promise<unknown>
  onAdd: (interest: NewInterest) => Promise<unknown>
  busyId?: number | null
  adding?: boolean
}

export function InterestsView({
  interests,
  onChange,
  onAdd,
  busyId = null,
  adding = false,
}: Props) {
  const { t } = useTranslation()
  const form = useForm<InterestValues>({
    resolver: zodResolver(interestSchema),
    defaultValues: { topic: '', keywords: '', notes: '' },
  })

  return (
    <div className="grid gap-10">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">{t('interests.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('interests.hint')}</p>
        {interests.length === 0 ? (
          <p className="mt-4 text-muted-foreground">{t('interests.empty')}</p>
        ) : (
          <ul className="mt-2 divide-y">
            {interests.map((interest) => (
              <li key={interest.id}>
                <InterestItem
                  interest={interest}
                  onChange={onChange}
                  busy={busyId === interest.id}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
      <form
        className="grid gap-3"
        noValidate
        aria-label={t('interests.add')}
        onSubmit={(event) =>
          void form.handleSubmit(async (values) => {
            try {
              await onAdd({
                topic: values.topic,
                keywords: splitKeywords(values.keywords),
                notes: values.notes,
              })
              form.reset()
            } catch {
              // The page shows the problem; the form keeps what was typed.
            }
          })(event)
        }
      >
        <h2 className="text-lg font-semibold">{t('interests.add')}</h2>
        <div className="grid gap-2">
          <Label htmlFor="new-topic">{t('interests.topic')}</Label>
          <Input
            id="new-topic"
            aria-invalid={form.formState.errors.topic ? true : undefined}
            {...form.register('topic')}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="new-keywords">{t('interests.keywords')}</Label>
          <Input id="new-keywords" {...form.register('keywords')} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="new-notes">{t('interests.notes')}</Label>
          <Textarea
            id="new-notes"
            rows={3}
            placeholder={t('interests.notesPlaceholder')}
            {...form.register('notes')}
          />
        </div>
        <Button type="submit" className="w-fit" disabled={adding}>
          {t('interests.addSubmit')}
        </Button>
      </form>
    </div>
  )
}

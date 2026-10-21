import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'

import type { InterestChange, InterestOut } from '@/client/types.gen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

import { interestSchema, type InterestValues, splitKeywords } from './interest-form'

interface Props {
  interest: InterestOut
  onChange: (interest: InterestOut, change: InterestChange) => Promise<unknown>
  busy?: boolean
}

export function InterestItem({ interest, onChange, busy = false }: Props) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const form = useForm<InterestValues>({
    resolver: zodResolver(interestSchema),
    values: {
      topic: interest.topic,
      keywords: interest.keywords.join(', '),
      notes: interest.notes,
    },
  })
  const id = `interest-${String(interest.id)}`

  if (editing) {
    return (
      <form
        className="grid gap-3 py-3"
        noValidate
        aria-label={interest.topic}
        onSubmit={(event) =>
          void form.handleSubmit(async (values) => {
            try {
              await onChange(interest, {
                topic: values.topic,
                keywords: splitKeywords(values.keywords),
                notes: values.notes,
              })
              setEditing(false)
            } catch {
              // The page shows the problem; the form keeps what was typed.
            }
          })(event)
        }
      >
        <div className="grid gap-2">
          <Label htmlFor={`${id}-topic`}>{t('interests.topic')}</Label>
          <Input id={`${id}-topic`} {...form.register('topic')} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`${id}-keywords`}>{t('interests.keywords')}</Label>
          <Input id={`${id}-keywords`} {...form.register('keywords')} />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`${id}-notes`}>{t('interests.notes')}</Label>
          <Textarea
            id={`${id}-notes`}
            rows={4}
            placeholder={t('interests.notesPlaceholder')}
            {...form.register('notes')}
          />
        </div>
        <div className="flex gap-2">
          <Button type="submit" size="sm" disabled={busy}>
            {t('app.save')}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              form.reset()
              setEditing(false)
            }}
          >
            {t('app.cancel')}
          </Button>
        </div>
      </form>
    )
  }

  return (
    <article className="grid gap-1 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-medium">{interest.topic}</h3>
        <span className="text-xs text-muted-foreground">
          {interest.active ? t('interests.active') : t('interests.inactive')}
        </span>
      </div>
      {interest.keywords.length > 0 ? (
        <p className="text-sm text-muted-foreground">{interest.keywords.join(', ')}</p>
      ) : null}
      <p className="text-sm whitespace-pre-line">{interest.notes || t('interests.noNotes')}</p>
      <div className="mt-1 flex gap-2">
        <Button
          size="sm"
          variant="outline"
          aria-label={`${t('app.edit')}: ${interest.topic}`}
          onClick={() => {
            setEditing(true)
          }}
        >
          {t('app.edit')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy}
          aria-label={`${interest.active ? t('interests.deactivate') : t('interests.activate')}: ${interest.topic}`}
          onClick={() =>
            void onChange(interest, { active: !interest.active }).catch(() => undefined)
          }
        >
          {interest.active ? t('interests.deactivate') : t('interests.activate')}
        </Button>
      </div>
    </article>
  )
}

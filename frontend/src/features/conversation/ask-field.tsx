import { useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

import { QUESTION_CHARS } from './lib'

interface Props {
  text: string
  onText: (text: string) => void
  onSend: () => void
  /** False while an answer is in progress or asking is refused. */
  canSend: boolean
  /** Why asking is refused, shown above the field. */
  reason?: string | null
}

/** The question field at the bottom of the screen. It stays enabled while an
 * answer is written, so it keeps focus; only sending waits. */
export function AskField({ text, onText, onSend, canSend, reason }: Props) {
  const { t } = useTranslation()
  const field = useRef<HTMLTextAreaElement>(null)
  const ready = canSend && text.trim() !== ''
  const send = () => {
    if (!ready) return
    onSend()
    // The next question follows without another tap on the field.
    field.current?.focus()
  }
  return (
    <form
      className="sticky bottom-0 mt-6 bg-background pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
    >
      {reason ? <p className="mb-2 text-sm text-muted-foreground">{reason}</p> : null}
      <div className="flex items-end gap-2">
        <Textarea
          ref={field}
          aria-label={t('conversation.placeholder')}
          placeholder={t('conversation.placeholder')}
          maxLength={QUESTION_CHARS}
          rows={1}
          className="max-h-40 min-h-10"
          value={text}
          onChange={(event) => {
            onText(event.target.value)
          }}
          onKeyDown={(event) => {
            // Enter sends, Shift+Enter breaks the line; not while composing.
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              send()
            }
          }}
        />
        <Button type="submit" className="h-10" disabled={!ready}>
          {t('conversation.send')}
        </Button>
      </div>
    </form>
  )
}

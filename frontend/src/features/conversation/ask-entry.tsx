import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'

/** The way into an article's conversation, with its number of questions. */
export function AskEntry({ articleId, count }: { articleId: number; count: number }) {
  const { t } = useTranslation()
  return (
    <div className="mx-auto mt-6 max-w-prose">
      <Button variant="outline" asChild>
        <Link to="/articles/$id/chat" params={{ id: String(articleId) }}>
          {count > 0 ? t('conversation.askCount', { count }) : t('conversation.ask')}
        </Link>
      </Button>
    </div>
  )
}

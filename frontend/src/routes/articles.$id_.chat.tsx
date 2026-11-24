import { createFileRoute } from '@tanstack/react-router'

import { ConversationPage } from '@/features/conversation/conversation-page'

// `$id_`: a page of its own, not nested in the brief's.
export const Route = createFileRoute('/articles/$id_/chat')({
  component: ChatPage,
})

function ChatPage() {
  const { id } = Route.useParams()
  const articleId = Number(id)
  return <ConversationPage key={id} articleId={articleId} />
}

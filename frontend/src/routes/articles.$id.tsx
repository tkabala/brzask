import { createFileRoute } from '@tanstack/react-router'

import { BriefPage } from '@/features/brief/brief-page'

export const Route = createFileRoute('/articles/$id')({
  component: ArticlePage,
})

function ArticlePage() {
  const { id } = Route.useParams()
  // Fetched in the page, not a route loader: loaders run before the session gate.
  return <BriefPage key={id} articleId={Number(id)} />
}

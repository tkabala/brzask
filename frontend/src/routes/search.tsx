import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'

import { searchOptions } from '@/client/@tanstack/react-query.gen'
import { ProblemMessage } from '@/components/problem-message'
import { SearchView } from '@/features/search/search-view'

export const Route = createFileRoute('/search')({
  validateSearch: z.object({ q: z.string().optional() }),
  component: SearchPage,
})

function SearchPage() {
  const { q = '' } = Route.useSearch()
  const navigate = Route.useNavigate()
  const results = useQuery({ ...searchOptions({ query: { q } }), enabled: q !== '' })

  return (
    <>
      {/* Keyed by the query, so going back in history refills the box. */}
      <SearchView
        key={q}
        query={q}
        results={results.data ?? null}
        onSearch={(query) => void navigate({ search: { q: query } })}
      />
      {results.isError ? (
        <div className="mt-4">
          <ProblemMessage error={results.error} onRetry={() => void results.refetch()} />
        </div>
      ) : null}
    </>
  )
}

import type { SourceStatus } from '@/client/types.gen'

/** The statuses the source list can be narrowed to; pending ones have their own list. */
export const FILTERS = ['all', 'active', 'muted', 'rejected', 'dead'] as const satisfies readonly (
  SourceStatus | 'all'
)[]
export type Filter = (typeof FILTERS)[number]

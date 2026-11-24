import { client } from '@/client/client.gen'
import type { DeepDiveRef } from '@/client/types.gen'

/** Refetch every 5 s while something is being written. */
export const ACTIVE_REFETCH_MS = 5000

export const isActive = (dive: Pick<DeepDiveRef, 'status'>) =>
  dive.status === 'queued' || dive.status === 'running'

/** Where a dive's Markdown export is served (relative to the API's base URL). */
export function markdownUrl(diveId: number): string {
  return `${client.getConfig().baseUrl ?? ''}/api/v1/deep-dives/${String(diveId)}/markdown`
}

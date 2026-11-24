import { client } from '@/client/client.gen'
import type { ConversationMessageOut } from '@/client/types.gen'

/** Refetch every 5 s while an answer is being written or searched for. */
export const BUSY_REFETCH_MS = 5000

/** The longest question the API accepts. */
export const QUESTION_CHARS = 1000

export const isBusy = (message: Pick<ConversationMessageOut, 'status'>) =>
  message.status === 'answering' || message.status === 'searching'

/** The last message when it is an answer: the one retry, search and suggestions act on. */
export function latestAnswer(
  messages: readonly ConversationMessageOut[],
): ConversationMessageOut | undefined {
  const last = messages.at(-1)
  return last?.role === 'assistant' ? last : undefined
}

/** Where a conversation's Markdown export is served (relative to the API's base URL). */
export function markdownUrl(articleId: number): string {
  return `${client.getConfig().baseUrl ?? ''}/api/v1/articles/${String(articleId)}/conversation/markdown`
}

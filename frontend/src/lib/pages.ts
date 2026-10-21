/** Cursor pagination with useInfiniteQuery: the next page starts at `next_cursor`. */
export function nextCursor(page: { next_cursor: string | null }): string | null {
  return page.next_cursor
}

/** The first page: no cursor. Not null, which the generated query functions
 * would take for request options, since `typeof null` is "object". */
export const FIRST_PAGE = {}
